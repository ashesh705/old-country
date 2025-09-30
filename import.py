# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "loguru",
#     "niquests",
#     "pydantic",
# ]
# ///

import argparse
import asyncio
import csv
from collections.abc import Iterable
from datetime import date, datetime
from pathlib import Path
from tempfile import gettempdir
from typing import Optional

from loguru import logger
from decimal import Decimal
from functools import total_ordering
from typing import Any

from pydantic import BaseModel, Field, validator
from itertools import chain
from typing import TypedDict

from niquests import AsyncSession

MIN_DATE = date(2020, 1, 1)
DATE_FORMAT = "%d-%m-%Y"

@total_ordering
class NAV(BaseModel):
    scheme_code: int
    scheme_name: str = ""
    nav_date: date = Field(alias="date")
    nav: Decimal = Field(ge=0)

    @property
    def _key(self) -> tuple[int, date]:
        return self.scheme_code, self.nav_date

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, NAV):
            raise ValueError("Cannot compare a NAV object with any other type")

        return self._key == other._key

    def __lt__(self, other: "NAV") -> bool:
        return self._key < other._key

    @validator("nav_date", pre=True)
    def get_nav_date(cls, v: str) -> date:
        return datetime.strptime(v, DATE_FORMAT).date()

class APIOutputNode(TypedDict):
    """Single node of NAV API output"""

    date: str
    nav: str


class APIOutput(TypedDict):
    """Representation of NAV API output format"""

    data: list[APIOutputNode]

class _NAVImporter:
    """Import NAVs for a single mutual fund"""

    _URL = "https://api.mfapi.in/mf/{code}"

    def __init__(self, scheme_code: int, session: AsyncSession) -> None:
        self.scheme_code = scheme_code
        self.session = session

    async def _get_raw_stream(self) -> APIOutput:
        """Get the raw response from NAV API"""

        scheme_url = self._URL.format(code=self.scheme_code)

        logger.debug(f"Calling URL: {scheme_url}")
        response = await self.session.get(scheme_url)
        resp: APIOutput = response.json()
        return resp

    async def _read_stream(self) -> list[APIOutputNode]:
        """Read the raw response from NAV API"""

        stream = await self._get_raw_stream()
        return stream["data"]

    async def get_nav(self) -> list[NAV]:
        """Return NAVs for the mutual fund"""

        raw = await self._read_stream()
        return list(map(self._transform, raw))

    def _transform(self, node: APIOutputNode) -> NAV:
        """Transform the raw API response into a NAV object"""

        return NAV(scheme_code=self.scheme_code, **node)
    
async def import_nav(scheme_codes: Iterable[int]) -> list[NAV]:
    """Import NAVs for provided list of mutual funds"""

    scheme_codes = list(scheme_codes)
    logger.info(
        f"Trying to fetch NAVs for {len(scheme_codes)} codes: {scheme_codes}"
    )

    async with AsyncSession() as session:
        data = await asyncio.gather(
            *map(
                lambda scheme_code: _NAVImporter(
                    scheme_code, session
                ).get_nav(),
                scheme_codes,
            )
        )

    return sorted(chain.from_iterable(data), reverse=True)

def to_date(s: str) -> date:
    """Convert string input into python native date"""

    return datetime.strptime(s, "%Y%m%d").date()

def get_output_file(file: Optional[str]) -> Path:
    """Get the output file to write the data"""

    if file is None:
        return Path(gettempdir()) / f"NAV_{date.today()}.csv"

    return Path(file)

def write_to_file(file: Path, data: Iterable[NAV]) -> None:
    """Write list of NAVs to the specified file"""

    data = list(data)

    with file.open("w", newline="") as f:
        w = csv.DictWriter(
            f, fieldnames=["scheme_code", "scheme_name", "nav_date", "nav"]
        )
        w.writerows([d.dict() for d in data])

    logger.info(f"Wrote {len(data)} rows to {file}")

async def main(inputs: argparse.Namespace) -> None:
    """Main control flow of the script"""

    scheme_codes: list[int] = inputs.codes
    nav_data = await import_nav(scheme_codes)

    min_date = inputs.min_date or MIN_DATE
    max_date = inputs.max_date or date.today()

    filtered_data = filter(
        lambda n: (n.nav_date >= min_date) and (n.nav_date <= max_date),
        nav_data,
    )

    out_file = get_output_file(inputs.out_file)
    write_to_file(out_file, filtered_data)

if __name__ == "__main__":
    parser = argparse.ArgumentParser("Fetch NAVs for a list of Mutual Funds")

    parser.add_argument(
        "--codes",
        nargs="+",
        type=int,
        required=True,
        help="List of AMFI scheme codes for the mutual funds",
    )

    parser.add_argument(
        "--min_date",
        type=to_date,
        help="Earliest date to fetch NAVs for, in YYYYMMDD format",
    )
    parser.add_argument(
        "--max-date",
        type=to_date,
        help="Latest date to fetch NAVs for, in YYYYMMDD format",
    )

    parser.add_argument(
        "--out_file", help="Full path of file to save the NAVs to"
    )

    args = parser.parse_args()
    asyncio.run(main(args))
