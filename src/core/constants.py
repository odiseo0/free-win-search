from datetime import timedelta, timezone

BASE_URL = "https://www.coolstuffinc.com/p/YuGiOh/"
REQUEST_TIMEOUT_SECONDS = 15
DELAY_BETWEEN_REQUESTS_SECONDS = 1.5
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
EXCEL_TEMPLATE_FILENAME = "Template.xlsx"
EXPORT_PLATFORM_NAME = "CoolStuffInc"
YGO_API_URL = "https://db.ygoprodeck.com/api/v7/cardinfo.php"
TZ = timezone(timedelta(hours=-4), name="America/Caracas")
