"""WoocommerceSink target sink class, which handles writing streams."""

from target_hotglue.client import HotglueSink
from requests_ntlm import HttpNtlmAuth
import backoff
import requests
import json
from singer_sdk.exceptions import RetriableAPIError
from target_hotglue.common import HGJSONEncoder
from datetime import datetime
import ast
import requests
import base64


class DynamicOnpremSink(HotglueSink):

    def __init__(
        self,
        target,
        stream_name,
        schema,
        key_properties,
    ) -> None:
        super().__init__(target, stream_name, schema, key_properties)

    @property
    def company_key(self):
        base_url = f"{self.config.get('url_base')}"
        if "api" in base_url:
            company_key = "companies"
        elif "OData" in base_url:
            company_key = "Company"
        return company_key

    @property
    def base_url(self):
        base_url = f"{self.config.get('url_base')}{self.company_key}"
        self.logger.info(f"BASE URL: {base_url}")
        return base_url

    @property
    def http_headers(self):
        return {}
    
    params = {"$format": "json"}
    
    def clean_convert(self, input):
        if isinstance(input, list):
            return [self.clean_convert(i) for i in input]
        elif isinstance(input, dict):
            output = {}
            for k, v in input.items():
                v = self.clean_convert(v)
                if isinstance(v, list):
                    output[k] = [i for i in v if (i)]
                elif v:
                    output[k] = v
            return output
        elif isinstance(input, datetime):
            return input.isoformat()
        elif input:
            return input
    
    def convert_date(self, date):
        converted_date = date.split("T")[0]
        return converted_date
    
    def request_api(self, http_method, endpoint=None, params={}, request_data=None, headers={}):
        """Request records from REST endpoint(s), returning response records."""
        resp = self._request(http_method, endpoint, params=params, headers=headers, request_data=request_data)
        return resp
    
    def get_endpoint(self, record, endpoint=None):
        #use subsidiary as company if passed, else use company from config
        company_id = record.get("subsidiary") or self.config.get("company_id")
        # escape apostrophe
        company_id = company_id.replace("'", "''")
        endpoint = endpoint or self.endpoint

        if self.company_key == "Company":
            return f"('{company_id}')" + endpoint
        elif self.company_key == "companies":
            return f"({company_id})" + endpoint
    
    @backoff.on_exception(
        backoff.expo,
        (RetriableAPIError, requests.exceptions.ReadTimeout),
        max_tries=5,
        factor=2,
    )
    def _request(
        self, http_method, endpoint, auth=None, params={}, request_data=None, headers={}
    ) -> requests.PreparedRequest:
        """Prepare a request object."""
        url = self.url(endpoint)
        headers.update(self.default_headers)
        headers.update({"Content-Type": "application/json"})

        if self.config.get("basic_auth") == True:
            auth = (self.config.get("username"), self.config.get("password"))
        else:
            auth = HttpNtlmAuth(self.config.get("username"), self.config.get("password"))        

        self.logger.info(f"MAKING {http_method} REQUEST")
        self.logger.info(f"URL {url} params {params} data {request_data}")
        response = requests.request(
            method=http_method,
            url=url,
            params=params,
            headers=headers,
            json=request_data,
            auth=auth
        )
        self.logger.info("response!!")
        self.logger.info(f"RESPONSE TEXT {response.text} STATUS CODE {response.status_code}")
        self.validate_response(response)
        return response

    def parse_objs(self, obj):
        try:
            try:
                return ast.literal_eval(obj)
            except:
                return json.loads(obj)
        except:
            return obj
    
    def process_custom_fields(self, custom_fields):
        output = {}
        if isinstance(custom_fields, str):
            custom_fields = self.parse_objs(custom_fields)
        
        if custom_fields:
            [
                output.update({cf.get("name"): cf.get("value")})
                for cf in custom_fields
            ]
        return output

    
    def upload_attachments(self, attachments, parent_id, endpoint, parent_type):
        if isinstance(attachments, str):
            attachments = self.parse_objs(attachments)
        for attachment in attachments:
            att_name = attachment.get("name")
            url = attachment.get("url")
            content = attachment.get("content")

            # make att payload
            att_payload = {
                "fileName": att_name,
                "parentId": parent_id,
                "parentType": parent_type
            }

            # fetch data from if there is no content
            if not content:
                if url:
                    response = requests.get(url)
                    data = base64.b64encode(response.content).decode()
                else:
                    att_path = f"{self.config.get('input_path')}/{attachment.get('id')}_{att_name}"
                    with open(att_path, "rb") as attach_file:
                        data = base64.b64encode(attach_file.read()).decode()
            else:
                data = attachment.get("content")
            
            content_payload = {"attachmentContent": data}

            # post attachments
            att = self.request_api(
                "POST",
                endpoint=endpoint,
                request_data=att_payload,
            )
            att_id = att.json().get("id")
            if att_id:
                att = self.request_api(
                    "PATCH",
                    endpoint=f"{endpoint}({att_id})/attachmentContent",
                    request_data=content_payload,
                    headers={"If-Match": "*"}
                )
                self.logger.info(f"Attachment for parent {parent_id} posted succesfully with id {att_id}")

    