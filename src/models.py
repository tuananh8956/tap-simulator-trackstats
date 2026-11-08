from typing import List, Optional
import time
from pydantic import BaseModel, Field, ConfigDict

class PetItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    
    id: Optional[str] = "pet_default"
    name: str = "Unknown Pet"
    rarity: str = "Common"
    multiplier: float = 1.0
    power: float = 0.0

class TelemetryPayload(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    
    userId: int = Field(..., alias="userId")
    currentTaps: int = Field(default=0, alias="currentTaps")
    totalTaps: int = Field(default=0, alias="totalTaps")
    currentRebirths: int = Field(default=0, alias="currentRebirths")
    totalRebirths: int = Field(default=0, alias="totalRebirths")
    currentWins: int = Field(default=0, alias="currentWins")
    totalWins: int = Field(default=0, alias="totalWins")
    currentCurrency: int = Field(default=0, alias="currentCurrency")
    equippedPets: List[PetItem] = Field(default_factory=list, alias="equippedPets")
    petInventoryCount: int = Field(default=0, alias="petInventoryCount")
    totalPetPower: float = Field(default=0.0, alias="totalPetPower")
    timestamp: float = Field(default_factory=lambda: time.time())

class AccountInfo(BaseModel):
    user_id: int
    username: str
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None
    is_tracking: bool = True
    created_at: Optional[str] = None
    last_seen: Optional[str] = None

class SessionSummary(BaseModel):
    session_id: str
    user_id: int
    start_time: float
    end_time: Optional[float] = None
    initial_taps: int = 0
    final_taps: int = 0
    taps_gained: int = 0
    initial_rebirths: int = 0
    final_rebirths: int = 0
    rebirths_gained: int = 0
    max_tps: float = 0.0
    avg_tps: float = 0.0
