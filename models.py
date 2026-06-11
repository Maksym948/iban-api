from pydantic import BaseModel, Field
from typing import List, Optional

class IBANRequest(BaseModel):
    iban: str = Field(..., description="IBAN to validate", examples=["UA213223130000026007233566001"])

class IBANResponse(BaseModel):
    valid: bool
    iban: str
    country_code: Optional[str] = None
    length: Optional[int] = None
    errors: List[str] = []
