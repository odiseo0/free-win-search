from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class CardNotFound:
    card_id: int


@dataclass(frozen=True, slots=True)
class CardListingNotFound:
    card_listing_id: int


@dataclass(frozen=True, slots=True)
class ScrapeJobNotFound:
    job_id: UUID
