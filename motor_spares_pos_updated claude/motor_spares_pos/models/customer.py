"""Customer entity used by the existing customer workflow."""

from dataclasses import dataclass
from typing import Optional


@dataclass
class Customer:
    id: Optional[int] = None
    customer_code: Optional[str] = None
    name: str = ""
    company: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    id_number: Optional[str] = None
    vehicle_make: Optional[str] = None
    vehicle_model: Optional[str] = None
    vehicle_registration: Optional[str] = None
    active: bool = True

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "customer_code": self.customer_code,
            "name": self.name,
            "company": self.company,
            "phone": self.phone,
            "email": self.email,
            "address": self.address,
            "city": self.city,
            "country": self.country,
            "id_number": self.id_number,
            "vehicle_make": self.vehicle_make,
            "vehicle_model": self.vehicle_model,
            "vehicle_registration": self.vehicle_registration,
            "active": self.active,
        }


@dataclass
class Vehicle:
    id: Optional[int] = None
    customer_id: int = 0
    registration_number: str = ""
    make: Optional[str] = None
    model: Optional[str] = None
    year: Optional[int] = None
    engine: Optional[str] = None
    vin: Optional[str] = None
    color: Optional[str] = None
    notes: Optional[str] = None
    active: bool = True

    def to_dict(self) -> dict:
        return self.__dict__.copy()
