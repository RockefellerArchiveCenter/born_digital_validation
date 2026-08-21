from pathlib import Path
from unittest import TestCase
from unittest.mock import ANY, call, patch

from src.clients import AuroraClient

from .helpers import MockResponse


class AuroraClientTests(TestCase):

    @patch('electronbonder.client.ElectronBond.authorize_oauth')
    def setUp(self, mock_authorize):
        mock_authorize.return_value = True
        self.baseurl = "https://aurora.org"
        self.oauth_client_baseurl = "https://oauth.com"
        self.oauth_client_id = "123456789"
        self.oauth_client_secret = "abcdefg"
        self.args = {
            'baseurl': self.baseurl,
            'oauth_client_baseurl': self.oauth_client_baseurl,
            'oauth_client_id': self.oauth_client_id,
            'oauth_client_secret': self.oauth_client_secret}
        self.client = AuroraClient(**self.args)

    @patch('electronbonder.client.ElectronBond.post')
    def test_create_event(self, mock_post):
        expected_data = {"foo": "bar"}
        mock_post.return_value = MockResponse(expected_data, 200)
        transfer_uri = '/transfers/12/'
        short_code = 'PBAGP'

        output = self.client.create_event(short_code, transfer_uri)

        self.assertEqual(output, expected_data)
        mock_post.assert_called_once_with(
            '/events/',
            json={"code": short_code, "transfer": transfer_uri},
            headers={"Content-Type": "application/json"})

    @patch('electronbonder.client.ElectronBond.post')
    def test_create_transfer(self, mock_post):
        expected_data = {"foo": "bar"}
        mock_post.return_value = MockResponse(expected_data, 200)
        org_id = '1'
        source_filetype = '.tar'
        source_filename = 'new_transfer.tar.gz'
        transfer_id = '1234-5678-9876-5432'
        source_size = '1234567'

        output = self.client.create_transfer(org_id, source_filetype, source_filename, transfer_id, source_size)

        self.assertEqual(output, expected_data)
        mock_post.assert_called_once_with(
            '/transfers/',
            json={
                "organization": org_id,
                "machine_file_path": source_filename,
                "machine_file_size": source_size,
                "machine_file_upload_time": ANY,
                "machine_file_identifier": transfer_id,
                "machine_file_type": source_filetype,
                "bag_it_name": str(Path(source_filename).stem)
            },
            headers={"Content-Type": "application/json"})

    @patch('electronbonder.client.ElectronBond.put')
    def test_update_transfer(self, mock_put):
        expected_data = {"foo": "bar"}
        mock_put.return_value = MockResponse(expected_data, 200)
        transfer_uri = '/transfers/12/'
        data = {"baz": "buzz"}

        output = self.client.update_transfer(transfer_uri, data)

        self.assertEqual(output, expected_data)
        mock_put.assert_called_once_with(
            transfer_uri,
            json=data,
            headers={"Content-Type": "application/json"})

    @patch('electronbonder.client.ElectronBond.get')
    def test_org_by_upload_target(self, mock_get):
        expected_org = {"id": "1", "bagit_profile": "https://aurora.rockarch.org/orgs/1/bagit_profile"}
        mock_get.return_value = MockResponse({"results": [expected_org]}, 200)
        upload_target = 'rac-auroraprod-archivalrepository-upload'

        returned_org = self.client.org_by_upload_target(upload_target)

        self.assertEqual(returned_org, expected_org)
        mock_get.assert_called_once_with(
            "/orgs/find_by_upload_target",
            params={"upload_target": upload_target})

    @patch('src.clients.AuroraClient.pad_date')
    @patch('electronbonder.client.ElectronBond.post')
    def test_save_bag_info(self, mock_post, mock_pad_date):
        mock_pad_date.return_value = '2021-01-01'
        expected_data = {"foo": "bar"}
        mock_post.return_value = MockResponse(expected_data, 200)
        bag_info_data = {
            "External-Identifier": "12345",
            "Internal-Sender-Description": "Transfer description",
            "Title": "Transfer title",
            "Date-Start": "2021-01-01",
            "Date-End": "2021-12-31",
            "Record-Type": "grant records",
            "Bagging-Date": "2026-01-01",
            "Payload-Oxum": "123456.78",
            "Record-Creators": ["Mickey Mouse", "Daffy Duck"]
        }
        transfer_uri = '/transfers/12/'
        org_id = '1'
        output_data = {
            "source_organization": org_id,
            "external_identifier": "12345",
            "internal_sender_description": "Transfer description",
            "title": "Transfer title",
            "date_start": "2021-01-01",
            "date_end": "2021-01-01",
            "record_type": "grant records",
            "bagging_date": "2026-01-01",
            "bag_count": "",
            "bag_group_identifier": "",
            "payload_oxum": "123456.78",
            "bagit_profile_identifier": "",
            "creators_list": ["Mickey Mouse", "Daffy Duck"],
            "language_list": []
        }

        output = self.client.save_bag_info(transfer_uri, org_id, bag_info_data)

        self.assertEqual(output, expected_data)
        mock_post.assert_called_once_with(
            '/transfers/12/bag-info/',
            json=output_data,
            headers={"Content-Type": "application/json"})
        mock_pad_date.assert_has_calls([
            call('2021-01-01', 'start'),
            call('2021-12-31', 'end')])

    def test_pad_date(self):
        for date_string, date_type, expected in [
            ('1999', 'start', '1999-01-01'),
            ('1999-02', 'start', '1999-02-01'),
            ('1999-05-20', 'start', '1999-05-20'),
            ('1999', 'end', '1999-12-31'),
            ('1999-02', 'end', '1999-02-28'),
            ('1999-05-20', 'end', '1999-05-20'),
        ]:
            output = self.client.pad_date(date_string, date_type)
            self.assertEqual(output, expected)
