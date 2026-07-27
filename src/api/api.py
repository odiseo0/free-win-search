from fastapi import APIRouter

from src.api.cards import card_listings_router, cards_router

router = APIRouter()
router.include_router(cards_router, prefix="/cards")
router.include_router(card_listings_router, prefix="/card-listings")
