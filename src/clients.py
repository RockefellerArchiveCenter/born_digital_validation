import calendar
from datetime import datetime
from pathlib import Path

from electronbonder.client import ElectronBond


class AuroraClient:
    """Client to handle interactions with Aurora."""

    def __init__(self, baseurl, oauth_client_baseurl, oauth_client_id, oauth_client_secret):
        self.client = ElectronBond(
            baseurl=baseurl,
            oauth_client_baseurl=oauth_client_baseurl,
            oauth_client_id=oauth_client_id,
            oauth_client_secret=oauth_client_secret)
        if not self.client.authorize_oauth():
            raise Exception("Could not authorize Client ID {} in Aurora".format(oauth_client_id))

    def create_event(self, short_code, transfer_url):
        """Creates an event for a transfer in Aurora."""
        data = {
            "code": short_code,
            "transfer": transfer_url
        }
        resp = self.client.post(
            "/events/",
            json=data,
            headers={"Content-Type": "application/json"})
        if resp.status_code == 201:
            return resp.json()
        else:
            raise Exception(
                f"Error creating event in Aurora for with data {data}: {resp.status_code} {resp.text}")

    def create_transfer(self, org_id, source_filetype, source_filename, transfer_id, source_size):
        """Creates a new transfer in Aurora."""
        data = {
            "organization": f"/api/orgs/{org_id}/",
            "file_path": source_filename,
            "file_size": source_size,
            "file_upload_time": str(datetime.now()),
            "identifier": transfer_id,
            "file_type": source_filetype,
            "bag_it_name": str(Path(source_filename).stem)
        }
        resp = self.client.post(
            "/transfers/",
            json=data,
            headers={"Content-Type": "application/json"})
        if resp.status_code == 201:
            return resp.json()
        else:
            raise Exception(
                f"Error creating event in Aurora for with data {data}: {resp.status_code} {resp.text}")

    def update_transfer(self, full_url, data):
        """Updates data for an existing transfer"""
        package_id = full_url.rstrip('/').split('/')[-1]
        uri = f'/transfers/{package_id}/'
        resp = self.client.patch(
            uri,
            json=data,
            headers={"Content-Type": "application/json"})
        if resp.status_code == 200:
            return resp.json()
        else:
            raise Exception(
                f"Error updating transfer in Aurora for with data {data}: {resp.status_code} {resp.text}")

    def org_by_upload_target(self, upload_target):
        """Gets the organization matching an upload target."""
        resp = self.client.get("/orgs/find_by_upload_target", params={"upload_target": upload_target})
        if resp.status_code == 200:
            data = resp.json()
            if len(data['results']) != 1:
                raise Exception(
                    f"Expected to get exactly one organiztion for upload target {upload_target}, got {len(data['results'])} instead.")
            else:
                return data['results'][0]
        else:
            raise Exception(
                f"Error getting organization with upload target {upload_target}: {resp.status_code} {resp.text}")

    def save_bag_info(self, transfer_uri, bag_info):
        """Saves BagInfo data for a transfer."""
        data = {
            "external_identifier": bag_info.get("External-Identifier", ""),
            "internal_sender_description": bag_info.get("Internal-Sender-Description", ""),
            "title": bag_info.get("Title", ""),
            "date_start": self.pad_date(bag_info.get("Date-Start", ""), 'start'),
            "date_end": self.pad_date(bag_info.get("Date-End", ""), 'end'),
            "record_type": bag_info.get("Record-Type", ""),
            "bagging_date": bag_info.get("Bagging-Date", ""),
            "bag_count": bag_info.get("Bag-Count", ""),
            "bag_group_identifier": bag_info.get("Bag-Group-Identifier", ""),
            "payload_oxum": bag_info.get("Payload-Oxum", ""),
            "bagit_profile_identifier": bag_info.get("BagIt-Profile-Identifier", ""),
            "creators_list": bag_info.get("Record-Creators", []),
            "language_list": bag_info.get("Language", [])}
        package_id = transfer_uri.rstrip('/').split('/')[-1]
        uri = f'/transfers/{package_id}/save_bag_info/'
        resp = self.client.post(
            uri,
            json=data,
            headers={"Content-Type": "application/json"})
        if resp.status_code == 201:
            return resp.json()
        else:
            raise Exception(
                f"Error saving bag-info data in Aurora for with data {data}: {resp.status_code} {resp.text}")

    def pad_date(self, date_string, date_type):
        """Pads incomplete start or end dates."""
        if len(date_string) == 4:
            if date_type == 'start':
                return f'{date_string}-01-01'
            return f'{date_string}-12-31'
        elif len(date_string) == 7:
            year, month = date_string.split('-')
            if date_type == 'end':
                day = calendar.monthrange(int(year), int(month))[1]
                return f'{year}-{month}-{day}'
            return f'{year}-{month}-01'
        return date_string
