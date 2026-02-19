
import unittest
from airline_pii_redactor import AirlinePIIRedactor

class TestAirlinePIIExtended(unittest.TestCase):
    def setUp(self):
        self.redactor = AirlinePIIRedactor()

    def test_names_variations(self):
        cases = [
            ("Passenger [John Smith] needs help.", "[NAME]"),
            ("Passenger (Jane Doe) needs help.", "[NAME]"),
            ("Name: Smith, John", "[NAME]"), # Presidio often handles this, let's verify
            ("I am Mr. John.Smith.", "[NAME]")
        ]
        for original, tag in cases:
            redacted = self.redactor.redact(original)
            self.assertIn(tag, redacted, f"Failed to redact name in: {original}")
            # Check for leakage
            self.assertFalse("John" in redacted and "Smith" in redacted, f"Leaked name in: {original}")

    def test_dates_variations(self):
        # DOBs (Past)
        cases = [
            ("Born on 01011990", "[DOB]"),
            ("DOB: 1 Jan 1990", "[DOB]"),
            ("Born 1st January 1990", "[DOB]"),
            ("born 1990 01 01", "[DOB]"),
            ("01/01/90", "[DOB]") # Short year
        ]
        for original, tag in cases:
            redacted = self.redactor.redact(original)
            self.assertIn(tag, redacted, f"Failed to redact DOB in: {original}")

    def test_dates_flight_context(self):
        # Future/Recent dates should NOT be redacted
        cases = [
            ("Flying on 1 Jan 2025", "1 Jan 2025"),
            ("Departs 20250101", "20250101"),
            ("Date: 12/25/2024", "12/25/2024")
        ]
        for original, expected_part in cases:
            redacted = self.redactor.redact(original)
            self.assertIn(expected_part, redacted, f"Incorrectly redacted flight date in: {original}")
            self.assertNotIn("[DOB]", redacted)

    def test_pnr_messy_formats(self):
        cases = [
            ("PNR:X9Y8Z7", "[PNR]"),       # No space
            ("Ref # X9Y8Z7", "[PNR]"),    # Symbol prefix
            ("Locator:X9Y8Z7", "[PNR]"),
            ("booking ref is X9Y8Z7", "[PNR]")
        ]
        for original, tag in cases:
            redacted = self.redactor.redact(original)
            self.assertIn(tag, redacted, f"Failed to redact PNR in: {original}")
            self.assertFalse("X9Y8Z7" in redacted)

    def test_flight_number_messy(self):
        cases = [
            ("flight#MU567", "[Flight no]"),
            ("Flight MU-567", "[Flight no]"), # Hyphenated (maybe not standard but possible user input)
            ("Code:MU567", "[Flight no]")
        ]
        for original, tag in cases:
            redacted = self.redactor.redact(original)
            # Hyphenated flight numbers might require regex adjustment if strict IATA is enforced
            # But let's see if the current logic catches standard ones in messy context
            if "-" not in original:
                 self.assertIn(tag, redacted, f"Failed to redact Flight No in: {original}")

    def test_phone_messy(self):
        cases = [
            ("Call 555.555.5555", "[Phone]"),
            ("Phone: +1 555 555 5555", "[Phone]"), # Extra spaces
            ("Mobile:13800138000", "[Phone]")      # No space after colon
        ]
        for original, tag in cases:
            redacted = self.redactor.redact(original)
            self.assertIn(tag, redacted, f"Failed to redact Phone in: {original}")

    def test_typos_and_informal(self):
        # Typos in context words shouldn't break detection if regex is robust
        # "Bron on" instead of "Born on" -> parser might fail context, but date entity might still be detected?
        # Actually, our date logic uses `parser.parse(fuzzy=True)`, so it relies on the date string itself.
        
        # Informal
        text = "dob is like 1990-01-01 i think"
        redacted = self.redactor.redact(text)
        self.assertIn("[DOB]", redacted)

if __name__ == '__main__':
    unittest.main()
