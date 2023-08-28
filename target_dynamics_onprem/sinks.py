"""Dynamics-onprem target sink class, which handles writing streams."""
import json
from target_dynamics_onprem.client import DynamicOnpremSink
from datetime import datetime


class Vendors(DynamicOnpremSink):
    """Dynamics-onprem target sink class."""

    endpoint = "/workflowVendors?$format=json"
    name = "Vendors"

    def preprocess_record(self, record: dict, context: dict) -> None:

        phoneNumbers = record.get("phoneNumber")
        address = record.get("addresses")
        mapping = {
            "name": record.get("vendorName"),
            "name2": record.get("contactName"),
            "eMail": record.get("emailAddress"),
            "phoneNumber": phoneNumbers[0] if phoneNumbers else None,
            "currencyCode": record.get("currency"),
        }

        if address:
            address = address[0]
            mapping["address"] = address.get("line1")
            mapping["address2"] = address.get("line2")
            mapping["city"] = address.get("city")
            mapping["county"] = address.get("state")
            mapping["countryRegionCode"] = address.get("country")
            mapping["postCode"] = address.get("postalCode")

        mapping = self.clean_convert(mapping)
        return mapping

    def upsert_record(self, record: dict, context: dict):
        state_updates = dict()
        if record:
            try:
                vendor = self.request_api(
                    "POST", endpoint=self.endpoint, request_data=record
                )
                vendor_id = vendor.json()["No"]
                self.logger.info(f"BuyOrder created succesfully with Id {vendor_id}")
            except:
                raise KeyError
            return vendor_id, True, state_updates
        
class Items(DynamicOnpremSink):
    """Dynamics-onprem target sink class."""

    endpoint = "/workflowItems?$format=json"
    name = "Items"

    def preprocess_record(self, record: dict, context: dict) -> None:
        mapping = {
            "description": record.get("name"),
            "type": record.get("type"),
            "reorderPoint": record.get("reorderPoint"),
            "taxGroupCode": record.get("taxCode"),
            "itemCategoryCode": record.get("category"),
        }
        if record.get("billItem", record.get("invoiceItem")):
            bill_item = record.get("billItem",record.get("invoiceItem"))
            bill_item = json.loads(bill_item)
            mapping["description2"] = bill_item.get("description")
            mapping["unitPrice"] = bill_item.get("unitPrice")

        mapping = self.clean_convert(mapping)
        return mapping

    def upsert_record(self, record: dict, context: dict):
        state_updates = dict()
        if record:
            try:
                item = self.request_api(
                    "POST", endpoint=self.endpoint, request_data=record
                )
                item_id = item.json()["No"]
                self.logger.info(f"Item created succesfully with Id {item_id}")
            except:
                raise KeyError
            return item_id, True, state_updates
        
class PurchaseOrder(DynamicOnpremSink):
    """Dynamics-onprem target sink class."""

    endpoint = "/purchaseDocuments?$format=json"
    name = "PurchaseOrders"

    def preprocess_record(self, record: dict, context: dict) -> None:
        dueDate = None
        if record.get("dueDate"):
            dueDate = self.convert_date(record.get("dueDate"))
        purchase_order_map = {
            "buyFromVendorNumber": record.get("vendorId"),
            "payToVendorNumber": record.get("vendorId"),
            "payToName": record.get("vendorName"),
            "currencyCode": record.get("currency"),
            "dueDate": dueDate,
            "locationCode": record.get("locationId"),
            "amount": record.get("totalAmount"),
            "documentType": "Order"
        }
        lines = []
        for line in record.get("lineItems"):
            serviceDate = None
            if line.get("serviceDate"):
                serviceDate = self.convert_date(line.get("serviceDate"))
            line_map = {
                "quantity": line.get("quantity"),
                "jobUnitPrice": line.get("unitPrice"),
                "jobLineDiscountAmount": line.get("discount"),
                "taxGroupCode": line.get("taxCode"),
                "description": line.get("productName"),
                "orderDate": serviceDate
            }
            lines.append(line_map)

        payload = {
            "purchase_order" : purchase_order_map,
            "lines": lines
        }
        mapping = self.clean_convert(payload)
        return mapping

    def upsert_record(self, record: dict, context: dict):
        state_updates = dict()
        if record:
            try:
                purchase_order = self.request_api(
                    "POST", endpoint=self.endpoint, request_data=record.get("purchase_order")
                )
                purchase_order = purchase_order.json()
                if purchase_order:
                    for line in record.get("lines"):
                        line["documentType"] = purchase_order.get("documentType")
                        line["documentNumber"] = purchase_order.get("number")
                        purchase_order_lines = self.request_api(
                            "POST", endpoint="/purchaseDocumentLines?$format=json", request_data=line
                        )
                purchase_order_id = purchase_order["number"]
                self.logger.info(f"purchase_order created succesfully with Id {purchase_order_id}")
            except:
                raise KeyError
            return purchase_order_id, True, state_updates