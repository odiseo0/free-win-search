from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CardNotFound:
    card_id: int


@dataclass(frozen=True, slots=True)
class CardListingNotFound:
    card_listing_id: int
