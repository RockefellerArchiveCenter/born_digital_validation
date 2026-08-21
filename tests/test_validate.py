from pathlib import Path
from shutil import copyfile, copytree, rmtree
from unittest import TestCase
from unittest.mock import ANY, call, patch

import bagit
import boto3
from botocore.exceptions import ClientError
from moto import mock_aws

from src.clients import AuroraClient
from src.validate import (BagItError, DataTypeError, DownloadError,
                          FilenameError, FileTypeError, Validator)

ARGS = [
    'us-east-1',
    'born-digital-validation-s3-role-arn',
    'source_bucket',
    'destination_bucket',
    'new-transfer.tar.gz',
    '12345678',
    '/validation',
    'https://aurora.rockarch.org/api',
    'https://oauth.org/',
    '12345678987654321',
    'a12bc3d4e5f6g7h8i9']


class ValidatorTests(TestCase):

    @patch('electronbonder.client.ElectronBond.authorize_oauth')
    def setUp(self, mock_authorize):
        mock_authorize.return_value = True
        tmp_dir = ARGS[6]
        dir_path = Path(tmp_dir)
        if not dir_path.is_dir():
            dir_path.mkdir()
        self.validator = Validator(*ARGS)

    def set_up_fixture_file(self, fixture_name, target_path):
        """Sets up file fixtures."""
        fixture_path = Path("tests", "fixtures", fixture_name)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        copyfile(fixture_path, target_path)

    def set_up_fixture_dir(self, fixture_dir, target_path):
        """Sets up directory fixtures."""
        fixture_path = Path("tests", "fixtures", fixture_dir)
        copytree(fixture_path, target_path)

    def test_init(self):
        """Asserts Validator init method sets attributes correctly."""
        self.assertEqual(self.validator.s3_role_arn, 'born-digital-validation-s3-role-arn')
        self.assertEqual(self.validator.region, 'us-east-1')
        self.assertEqual(self.validator.source_bucket, 'source_bucket')
        self.assertEqual(self.validator.destination_bucket, 'destination_bucket')
        self.assertEqual(self.validator.source_filename, 'new-transfer.tar.gz')
        self.assertEqual(self.validator.source_size, '12345678')
        self.assertTrue(isinstance(self.validator.transfer_id, str))
        self.assertEqual(self.validator.tmp_dir, '/validation')
        self.assertEqual(self.validator.service_name, 'born_digital_validation')
        self.assertTrue(isinstance(self.validator.aurora_client, AuroraClient))

    @patch('src.clients.AuroraClient.org_by_upload_target')
    @patch('src.validate.Validator.get_filetype')
    @patch('src.clients.AuroraClient.create_transfer')
    @patch('src.clients.AuroraClient.create_event')
    @patch('src.validate.Validator.download_bag')
    @patch('src.validate.Validator.extract_bag')
    @patch('src.validate.Validator.validate_filename')
    @patch('src.validate.Validator.validate_bag')
    @patch('src.clients.AuroraClient.update_transfer')
    @patch('src.validate.Validator.validate_metadata')
    @patch('src.clients.AuroraClient.save_bag_info')
    @patch('src.validate.move')
    @patch('src.validate.Validator.compress_transfer')
    @patch('src.validate.Validator.cleanup_binaries')
    def test_run(self, mock_cleanup, mock_compress, mock_move, mock_save_bag_info, mock_validate_metadata, mock_update_transfer,
                 mock_validate_bag, mock_validate_filename, mock_extract_bag, mock_download, mock_create_event,
                 mock_create_transfer, mock_filetype, mock_org):
        """Asserts correct methods are called by run method."""
        bagit_profile_url = "https://aurora.rockarch.org/orgs/1/bagit_profile"
        new_transfer_url = "https://aurora.rockarch.org/transfers/1"
        mock_org.return_value = {"id": "1", "bagit_profile": bagit_profile_url}
        mock_filetype.return_value = "tar"
        mock_create_transfer.return_value = {"url": new_transfer_url}
        mock_download.return_value = Path("/downloaded")
        mock_extract_bag.return_value = Path("/extracted")
        mock_validate_bag.return_value = "this is a manifest"
        mock_validate_metadata.return_value = {"foo": "bar"}

        self.validator.run()

        mock_org.assert_called_once_with(self.validator.source_bucket)
        mock_filetype.assert_called_once_with(self.validator.source_filename)
        mock_create_transfer.assert_called_once_with('1', 'tar', 'new-transfer.tar.gz', ANY, 'source_bucket', '12345678')
        mock_download.assert_called_once_with(self.validator.source_filename)
        mock_extract_bag.assert_called_once_with('tar', Path("/downloaded"))
        mock_validate_filename.assert_called_once_with(Path("/extracted"))
        mock_validate_bag.assert_called_once_with(Path("/extracted"))
        mock_validate_metadata.assert_called_once_with(Path("/extracted"), bagit_profile_url)
        mock_save_bag_info.assert_called_once_with(new_transfer_url, '1', {"foo": "bar"})
        mock_move.assert_called_once_with(Path("/extracted"), Path(self.validator.tmp_dir, self.validator.transfer_id))
        mock_compress.assert_called_once_with(Path(self.validator.tmp_dir, self.validator.transfer_id))
        mock_cleanup.assert_called_once_with(self.validator.source_filename)
        mock_update_transfer.assert_has_calls([
            call(new_transfer_url, {'manifest': 'this is a manifest'}),
            call(new_transfer_url, {'bag_it_valid': True, 'process_status': 'Validated'})])
        mock_create_event.assert_has_calls([
            call('ASAVE', new_transfer_url),
            call('PBAG', new_transfer_url),
            call('PBAGP', new_transfer_url),
            call('APASS', new_transfer_url)])

    @patch('src.clients.AuroraClient.org_by_upload_target')
    @patch('src.validate.Validator.get_filetype')
    @patch('src.clients.AuroraClient.create_transfer')
    @patch('src.clients.AuroraClient.create_event')
    @patch('src.validate.Validator.download_bag')
    @patch('src.validate.Validator.extract_bag')
    @patch('src.validate.Validator.validate_filename')
    @patch('src.validate.Validator.validate_bag')
    @patch('src.clients.AuroraClient.update_transfer')
    @patch('src.validate.Validator.validate_metadata')
    @patch('src.clients.AuroraClient.save_bag_info')
    @patch('src.validate.move')
    @patch('src.validate.Validator.compress_transfer')
    @patch('src.validate.Validator.cleanup_binaries')
    def test_run_with_exception(self, mock_cleanup, mock_compress, mock_move, mock_save_bag_info, mock_validate_metadata, mock_update_transfer,
                                mock_validate_bag, mock_validate_filename, mock_extract_bag, mock_download, mock_create_event,
                                mock_create_transfer, mock_filetype, mock_org):
        """Asserts exceptions are correctly handled."""
        bagit_profile_url = "https://aurora.rockarch.org/orgs/1/bagit_profile"
        new_transfer_url = "https://aurora.rockarch.org/transfers/1"
        mock_org.return_value = {"id": "1", "bagit_profile": bagit_profile_url}
        mock_filetype.return_value = "tar"
        mock_create_transfer.return_value = {"url": new_transfer_url}
        mock_download.side_effect = DownloadError("foo")

        self.validator.run()

        mock_org.assert_called_once_with(self.validator.source_bucket)
        mock_filetype.assert_called_once_with(self.validator.source_filename)
        mock_create_transfer.assert_called_once_with('1', 'tar', 'new-transfer.tar.gz', ANY, 'source_bucket', '12345678')
        mock_download.assert_called_once_with(self.validator.source_filename)
        mock_extract_bag.assert_not_called()
        mock_validate_filename.assert_not_called()
        mock_validate_bag.assert_not_called()
        mock_validate_metadata.assert_not_called()
        mock_save_bag_info.assert_not_called()
        mock_move.assert_not_called()
        mock_compress.assert_not_called()
        mock_cleanup.assert_not_called()
        mock_update_transfer.assert_has_calls([
            call('https://aurora.rockarch.org/transfers/1', {'additional_error_info': 'foo', 'process_status': 'Invalid'})])
        mock_create_event.assert_has_calls([
            call('ASAVE', new_transfer_url),
            call('DEXT', new_transfer_url)])

    def test_get_filetype(self):
        """Asserts filetype is correctly parsed."""
        for filepath, expected_filetype in [
                ('foo.tar', 'tar'),
                ('subdir/foo.tar', 'tar'),
                ('foo.tar.gz', 'tar.gz'),
                ('foo.zip', 'zip')]:
            filetype = self.validator.get_filetype(filepath)
            self.assertEqual(filetype, expected_filetype)

        with self.assertRaises(FileTypeError):
            self.validator.get_filetype("foo.txt")

    @mock_aws
    def test_download_bag(self):
        """Asserts file is downloaded correctly."""
        expected_path = Path(self.validator.tmp_dir, self.validator.source_filename)
        s3 = boto3.client('s3', region_name='us-east-1')
        s3.create_bucket(Bucket=self.validator.source_bucket)
        s3.put_object(Bucket=self.validator.source_bucket, Key=self.validator.source_filename, Body='')

        downloaded = self.validator.download_bag()
        self.assertEqual(downloaded, expected_path)
        self.assertTrue(expected_path.is_file())

    def test_extract_bag_tar(self):
        """Asserts tarballed bag is extracted correctly."""
        tmp_path = Path(self.validator.tmp_dir, self.validator.source_filename)
        self.set_up_fixture_file(self.validator.source_filename, tmp_path)

        extracted_path = self.validator.extract_bag('tar.gz', tmp_path)

        self.assertEqual(extracted_path, Path(self.validator.tmp_dir, 'new-transfer'))
        self.assertTrue(extracted_path.is_dir())

    def test_extract_bag_zip(self):
        """Asserts zipped bag is extracted correctly."""
        tmp_path = Path(self.validator.tmp_dir, "new-transfer.zip")
        self.set_up_fixture_file("new-transfer.zip", tmp_path)

        extracted_path = self.validator.extract_bag('zip', tmp_path)

        self.assertEqual(extracted_path, Path(self.validator.tmp_dir, 'new-transfer'))
        self.assertTrue(extracted_path.is_dir())

    def test_validate_filename(self):
        """Asserts filenames are validated as expected."""
        for fn in ['This has spaces', 'questionmark?', 'colon:', 'exclamation!']:
            with self.assertRaises(FilenameError):
                self.validator.validate_filename(Path(fn))

    def test_validate_bag(self):
        """Asserts bag validation is successful or raises expected exceptions on failure."""
        tmp_path = Path(self.validator.tmp_dir, 'new-transfer')
        self.set_up_fixture_dir('new-transfer', tmp_path)

        self.validator.validate_bag(tmp_path)

        rmtree(Path(tmp_path, 'data'))
        with self.assertRaises(BagItError):
            self.validator.validate_bag(tmp_path)

    @patch('src.validate.Validator.validate_bag_it_profile')
    @patch('src.validate.Validator.validate_dates')
    @patch('src.validate.Validator.validate_languages')
    def test_validate_metadata(self, mock_language, mock_dates, mock_profile):
        """Asserts metadata validation methods are called with correct args."""
        tmp_path = Path(self.validator.tmp_dir, 'new-transfer')
        self.set_up_fixture_dir('new-transfer', tmp_path)
        org_bagit_profile_url = 'https://aurora.rockarch.org/api/orgs/1/bagit_profile'
        expected_bag_info = {
            'Bag-Software-Agent': 'bagit.py v1.8.1 <https://github.com/LibraryOfCongress/bagit-python>',
            'Bagging-Date': '2023-03-14',
            'Payload-Oxum': '20.1'}

        bag_info = self.validator.validate_metadata(tmp_path, org_bagit_profile_url)

        self.assertEqual(bag_info, expected_bag_info)
        mock_profile.assert_called_once_with(ANY, org_bagit_profile_url)
        mock_dates.assert_called_once_with(expected_bag_info)
        mock_language.assert_called_once_with(None)

    @patch('bagit_profile.Profile.__init__')
    @patch('bagit_profile.Profile.validate')
    def test_validate_bag_it_profile(self, mock_validate, mock_init):
        """Asserts BagIt Profiles are validated as expected"""
        mock_init.return_value = None
        mock_validate.return_value = True
        bag = bagit.Bag(Path("tests", "fixtures", "new-transfer"))
        profile_url = "https://aurora.rockarch.org/api/orgs/1/bagit_profile"

        self.validator.validate_bag_it_profile(bag, profile_url)

        mock_init.assert_called_once_with(profile_url)
        mock_validate.assert_called_once_with(bag)

    def test_validate_dates(self):
        """Asserts dates are validated as expected."""
        bag_info = {"Date-Start": "2020", "Date-End": "2020-01", "Bagging-Date": "2020-01-12"}
        self.validator.validate_dates(bag_info)

        with self.assertRaises(DataTypeError):
            self.validator.validate_dates({"Date-Start": "foo"})

    def test_validate_languages(self):
        """Asserts languages are validated as expected."""
        self.validator.validate_languages(None)
        self.validator.validate_languages([])
        self.validator.validate_languages('eng')
        self.validator.validate_languages(['eng', 'spa'])

        with self.assertRaises(DataTypeError):
            self.validator.validate_languages('foo')

    def test_compress_transfer(self):
        """Asserts transfer is compressed at correct location."""
        tmp_path = Path(self.validator.tmp_dir, 'new-transfer')
        self.set_up_fixture_dir('new-transfer', tmp_path)

        compressed_path = self.validator.compress_transfer(tmp_path, self.validator.source_filename)

        self.assertEqual(compressed_path, Path(self.validator.tmp_dir, self.validator.source_filename))
        self.assertTrue(compressed_path.is_file())

    @mock_aws
    def test_move_to_destination(self):
        """Asserts correct files are moved to correct location."""
        tmp_path = Path(self.validator.tmp_dir, self.validator.source_filename)
        self.set_up_fixture_file(self.validator.source_filename, tmp_path)
        s3 = boto3.client('s3', region_name='us-east-1')
        s3.create_bucket(Bucket=self.validator.destination_bucket)

        self.validator.move_to_destination(tmp_path)
        s3.head_object(
            Bucket=self.validator.destination_bucket,
            Key=self.validator.source_filename)

    @mock_aws
    def test_cleanup_binaries(self):
        """Asserts that binaries are cleaned up properly."""
        s3 = boto3.client('s3', region_name='us-east-1')
        s3.create_bucket(Bucket=self.validator.source_bucket)
        s3.put_object(
            Bucket=self.validator.source_bucket,
            Key=self.validator.source_filename,
            Body='')

        self.validator.cleanup_binaries(self.validator.source_filename)
        with self.assertRaises(ClientError):
            s3.head_object(
                Bucket=self.validator.source_bucket,
                Key=self.validator.source_filename)

    def tearDown(self):
        tmp_dir = ARGS[6]
        rmtree(tmp_dir)
