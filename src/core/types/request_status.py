from enum import StrEnum


class RequestStatus(StrEnum):
    DRAFT = "draft"
    REQUESTED = "requested"
    CONFIRMED = "confirmed"
    PAID = "paid"
    ORDERED = "ordered"
