"""Isolated Phase 4 CRM regression tests."""
import shutil
import tempfile
import unittest
from pathlib import Path
from database.db import configure_database
from models.customer import Customer, Vehicle
from models.product import Product
from services.customer_service import CustomerService
from services.product_service import ProductService
from services.sales_service import SalesService


class Phase4Tests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(tempfile.mkdtemp(prefix='pos_phase4_'))
        configure_database(str(self.directory / 'crm.db'))
        self.crm = CustomerService()
        self.customer = self.crm.create_customer(Customer(name='CRM Customer', phone='0771111111', email='crm@example.test', company='Michoe'))

    def tearDown(self): shutil.rmtree(self.directory, ignore_errors=True)

    def test_customer_code_search_edit_archive_restore_and_duplicate(self):
        self.assertEqual('CUS-000001', self.customer.customer_code)
        self.assertEqual(self.customer.id, self.crm.search_customers('Michoe')[0].id)
        self.customer.city = 'Harare'; self.crm.update_customer(self.customer)
        self.assertEqual('Harare', self.crm.get_customer(self.customer.id).city)
        with self.assertRaises(ValueError): self.crm.create_customer(Customer(name='Duplicate', phone='0771111111'))
        self.crm.archive_customer(self.customer.id); self.assertFalse(self.crm.search_customers('CRM Customer'))
        self.crm.restore_customer(self.customer.id); self.assertTrue(self.crm.search_customers('CRM Customer'))

    def test_multiple_vehicles_archive_restore_and_sale_history(self):
        vehicle = self.crm.create_vehicle(Vehicle(customer_id=self.customer.id, registration_number='ACR-1234', make='Toyota', model='Corolla', vin='VIN-CRM'))
        self.crm.create_vehicle(Vehicle(customer_id=self.customer.id, registration_number='ACR-5678', make='Honda'))
        self.assertEqual(2, len(self.crm.list_vehicles(self.customer.id)))
        self.assertEqual(vehicle.id, self.crm.search_vehicles('VIN-CRM')[0].id)
        product_id = ProductService().create_product(Product(part_no='CRM-PART', description='CRM Part', selling_price=20, cost_price=10, quantity_on_hand=3))
        sale = SalesService().create_sale(customer_id=self.customer.id, customer_name=self.customer.name, vehicle_registration=vehicle.registration_number, vehicle_id=vehicle.id, user_id=1, cashier_name='Administrator')
        SalesService().add_item_to_sale(sale, product_id, 1); SalesService().add_payment(sale, 'CARD', sale.total, 'USD', sale.total); SalesService().complete_sale(sale)
        self.assertEqual('CRM-PART', self.crm.vehicle_history(vehicle.id)[0]['part_no'])
        vehicle.color = 'Blue'; self.crm.update_vehicle(vehicle); self.assertEqual('Blue', self.crm.get_vehicle(vehicle.id).color)
        self.crm.archive_vehicle(vehicle.id); self.assertFalse(self.crm.search_vehicles('ACR-1234'))
        self.crm.restore_vehicle(vehicle.id); self.assertTrue(self.crm.search_vehicles('ACR-1234'))


if __name__ == '__main__': unittest.main()