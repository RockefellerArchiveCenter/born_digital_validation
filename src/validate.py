import logging
import re
import tarfile
from os import getenv
from pathlib import Path
from shutil import move
from uuid import uuid4
from zipfile import ZipFile

import bagit
import bagit_profile
import boto3
from aws_assume_role_lib import assume_role
from iso639 import Lang

from .clients import AuroraClient

logging.basicConfig(
    level=int(getenv('LOGGING_LEVEL', logging.INFO)),
    format='%(filename)s::%(funcName)s::%(lineno)s %(message)s')
logging.getLogger("bagit").setLevel(logging.ERROR)


class ValidationError(BaseException):
    pass


class FileTypeError(ValidationError):
    def __init__(self, *args):
        super().__init__(*args)
        self.error_code = 'BDIR'


class DownloadError(ValidationError):
    def __init__(self, *args):
        super().__init__(*args)
        self.error_code = 'DEXT'


class ExtractError(ValidationError):
    def __init__(self, *args):
        super().__init__(*args)
        self.error_code = 'EXERR'


class FilenameError(ValidationError):
    def __init__(self, *args):
        super().__init__(*args)
        self.error_code = 'BFNM'


class BagItError(ValidationError):
    def __init__(self, *args):
        super().__init__(*args)
        self.error_code = 'GBERR'


class BagItProfileError(ValidationError):
    def __init__(self, *args):
        super().__init__(*args)
        self.error_code = 'RBERR'


class DataTypeError(ValidationError):
    def __init__(self, *args):
        super().__init__(*args)
        self.error_code = 'DTERR'


class Validator(object):
    """Validates digitized audio and moving image assets."""

    def __init__(self, region, s3_role_arn, source_bucket, destination_bucket, source_filename, source_size, tmp_dir, aurora_baseurl,
                 aurora_oauth_client_baseurl, aurora_oauth_client_id, aurora_oauth_client_secret):
        self.s3_role_arn = s3_role_arn
        self.region = region
        self.source_bucket = source_bucket
        self.destination_bucket = destination_bucket
        self.source_filename = source_filename
        self.source_size = source_size
        self.transfer_id = str(uuid4())
        self.tmp_dir = tmp_dir
        self.service_name = 'born_digital_validation'
        self.aurora_client = AuroraClient(
            aurora_baseurl,
            aurora_oauth_client_baseurl,
            aurora_oauth_client_id,
            aurora_oauth_client_secret)

    def run(self):
        """Main method which calls all other logic."""
        logging.debug(f'Validation process started for package {self.source_filename} from bucket {self.source_bucket}.')
        transfer_uri = None
        try:
            org = self.aurora_client.org_by_upload_target(self.source_bucket)
            filetype = self.get_filetype(self.source_filename)
            new_transfer = self.aurora_client.create_transfer(
                org['id'],
                filetype,
                self.source_filename,
                self.transfer_id,
                self.source_bucket,
                self.source_size)
            transfer_uri = new_transfer['url']
            self.aurora_client.create_event("ASAVE", transfer_uri)

            downloaded_path = self.download_bag(self.source_filename)
            # TODO virus checking
            extracted_path = self.extract_bag(filetype, downloaded_path)
            self.validate_filename(extracted_path)
            manifest = self.validate_bag(extracted_path)
            self.aurora_client.update_transfer(transfer_uri, {'manifest': manifest})
            self.aurora_client.create_event("PBAG", transfer_uri)
            bag_info = self.validate_metadata(extracted_path, org['bagit_profile'])
            self.aurora_client.save_bag_info(transfer_uri, org['id'], bag_info)
            self.aurora_client.create_event("PBAGP", transfer_uri)

            renamed_path = Path(self.tmp_dir, self.transfer_id)
            move(extracted_path, renamed_path)
            self.compress_transfer(renamed_path)

            self.aurora_client.update_transfer(
                transfer_uri,
                {
                    "bag_it_valid": True,
                    "process_status": "Validated"
                })
            self.aurora_client.create_event("APASS", transfer_uri)
            logging.info(f'Package {self.source_filename} successfully validated and assigned ID {self.transfer_id}.')
            self.cleanup_binaries(self.source_filename)
        except ValidationError as e:
            logging.exception(e)
            if (transfer_uri and getattr(e, 'error_code')):
                self.aurora_client.update_transfer(
                    transfer_uri,
                    {
                        "additional_error_info": str(e),
                        "process_status": "Invalid"
                    })
                self.aurora_client.create_event(e.error_code, transfer_uri)

    def get_client_with_role(self, resource, role_arn):
        """Gets Boto3 client which authenticates with a specific IAM role."""
        session = boto3.Session()
        assumed_role_session = assume_role(session, role_arn)
        return assumed_role_session.client(resource)

    def get_filetype(self, filepath):
        filetype = "".join(Path(filepath).suffixes).lstrip(".")
        if filetype not in ['zip', 'tar', 'tar.gz']:
            raise FileTypeError(f"File type {filetype} is not allowed.")
        return filetype

    def download_bag(self):
        """Downloads a streaming file from S3.

        Returns:
            downloaded_path (pathlib.Path): path of the downloaded file.
        """
        try:
            downloaded_path = Path(self.tmp_dir, self.source_filename)
            client = self.get_client_with_role('s3', self.s3_role_arn)
            Path(downloaded_path).parent.mkdir(parents=True, exist_ok=True)
            client.download_file(
                self.source_bucket,
                self.source_filename,
                downloaded_path)
            logging.debug(f'Package downloaded to {downloaded_path}.')
            return downloaded_path
        except Exception as e:
            raise DownloadError(f"Error downloading transfer: {e}")

    def extract_bag(self, filetype, file_path):
        """Extracts the contents of a TAR or ZIP file.

        Args:
            file_path (pathlib.Path): path of compressed file to extract.
        """
        extracted_path = Path(self.tmp_dir, file_path.stem.split('.')[0])  # Handles file extensions with multiple dots, like .tar.gz
        if filetype in ["tar", "tar.gz"]:
            try:
                tf = tarfile.open(file_path, "r:*")
                tf.extractall(self.tmp_dir)
                tf.close()
                logging.debug(f'Package {file_path} extracted to {self.tmp_dir}.')
            except Exception as e:
                raise ExtractError("Error extracting TAR file: {}".format(e))
        elif filetype == "zip":
            try:
                zf = ZipFile(file_path, "r")
                zf.extractall(self.tmp_dir)
                zf.close()
            except Exception as e:
                raise ExtractError("Error extracting ZIP file: {}".format(e))
        return extracted_path

    def validate_filename(self, file_path):
        is_invalid = re.search(r"[<>\:\"\!\|\?\ \*]", file_path.name)
        if is_invalid:
            raise FilenameError(f"Invalid filename: {file_path}")

    def validate_bag(self, bag_path):
        """Validates a bag.

        Args:
            bag_path (pathlib.Path): path of bagit Bag to validate.

        Raises:
            bagit.BagValidationError with the error in the `details` property.
        """
        try:
            bag = bagit.Bag(str(bag_path))
            bag.validate()
            logging.debug(f'Bag {bag_path} validated.')
            for filename in bag_path.rglob("manifest-*.txt"):
                with open(filename, "r") as manifest_file:
                    return manifest_file.read()
        except Exception as e:
            raise BagItError(e)

    def validate_metadata(self, bag_path, org_bagit_profile_url):
        bag = bagit.Bag(str(bag_path))
        self.validate_bag_it_profile(bag, org_bagit_profile_url)
        self.validate_dates(bag.info)
        self.validate_languages(bag.info.get("Language"))
        return bag.info

    def validate_bag_it_profile(self, bag, org_bagit_profile_url):
        profile = bagit_profile.Profile(org_bagit_profile_url)
        valid = profile.validate(bag)
        if not valid:
            raise BagItProfileError(profile.report.errors)

    def validate_dates(self, bag_info):
        dates = [v for k, v in bag_info.items() if k in ["Date-Start", "Date-End", "Bagging-Date"]]
        for d in dates:
            try:
                parts = [p for p in d.split('-')]
                if len(parts) >= 1 and len(parts) <= 3:
                    if len(parts) == 1:
                        assert len(parts[0]) == 4
                    elif len(parts) == 2:
                        assert len(parts[0]) == 4
                        assert len(parts[1]) == 2
                    else:
                        assert len(parts[0]) == 4
                        assert len(parts[1]) == 2
                        assert len(parts[2]) == 2
                else:
                    raise DataTypeError(f"Invalid date value: {d}")
            except Exception:
                raise DataTypeError(f"Invalid date value: {d}")

    def validate_languages(self, langz):
        if langz:
            if not isinstance(langz, list):
                langz = [langz]
            for lang in langz:
                try:
                    language = Lang(lang)
                    assert language.pt2b == lang
                except Exception:
                    raise DataTypeError(f"Invalid language value: {lang}")

    def compress_transfer(self, transfer_dir, tar_name):
        compressed_path = Path(self.tmp_dir, tar_name)
        with tarfile.open(str(compressed_path), "w:gz") as tar:
            tar.add(transfer_dir, arcname=compressed_path.stem)
        logging.debug(f'Compressed bag {compressed_path} created.')
        return compressed_path

    def move_to_destination(self, transfer_path):
        """"Moves validated assets to destination bucket.

        Args:
            transfer_path (pathlib.Path): path of tarballed transfer.
        """
        client = self.get_client_with_role('s3', self.s3_role_arn)
        client.upload_file(
            str(transfer_path),
            self.destination_bucket,
            str(transfer_path.name),
            ExtraArgs={'ContentType': 'application/gzip'})
        logging.debug(f'Transfer {self.transfer_id} moved to destination bucket {self.destination_bucket}.')

    def cleanup_binaries(self, bag_path):
        """Removes binaries after completion of successful or failed job.

        Args:
            bag_path (pathlib.Path): path of bagit Bag containing assets.
        """
        client = self.get_client_with_role('s3', self.s3_role_arn)
        client.delete_object(
            Bucket=self.source_bucket,
            Key=bag_path)
        logging.debug('Binaries cleaned up.')


if __name__ == '__main__':
    region = getenv('AWS_REGION')
    s3_role_arn = getenv('AWS_S3_ROLE_ARN')
    source_bucket = getenv('AWS_SOURCE_BUCKET')
    source_filename = getenv('SOURCE_FILENAME')
    source_size = getenv('SOURCE_SIZE')
    tmp_dir = getenv('TMP_DIR')
    destination_bucket = getenv('DESTINATION_BUCKET')
    aurora_baseurl = getenv('AURORA_BASEURL')
    aurora_oauth_client_baseurl = getenv('AURORA_OAUTH_CLIENT_BASEURL')
    aurora_oauth_client_id = getenv('AURORA_OAUTH_CLIENT_ID')
    aurora_oauth_client_secret = getenv('AURORA_OAUTH_CLIENT_SECRET')

    logging.debug('Validator instantiated.')

    Validator(
        region,
        s3_role_arn,
        source_bucket,
        destination_bucket,
        source_filename,
        source_size,
        tmp_dir,
        aurora_baseurl,
        aurora_oauth_client_baseurl, aurora_oauth_client_id, aurora_oauth_client_secret).run()
