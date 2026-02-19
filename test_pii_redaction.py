
import unittest
from airline_pii_redactor import AirlinePIIRedactor

class TestAirlinePIIRedaction(unittest.TestCase):
    def setUp(self):
        self.redactor = AirlinePIIRedactor()

    def test_names_english(self):
        text = "Passenger John Smith and Jane Doe are traveling."
        expected = "Passenger [NAME] and [NAME] are traveling."
        self.assertEqual(self.redactor.redact(text), expected)

    def test_names_chinese_hanzi(self):
        text = "Customer 李明 and 王伟 booked tickets."
        # Note: Presidio/HanLP might map these to [NAME] or [PERSON] -> [NAME]
        redacted = self.redactor.redact(text)
        self.assertTrue("[NAME]" in redacted)
        self.assertFalse("李明" in redacted)
        self.assertFalse("王伟" in redacted)

    def test_names_chinese_romanized_compound(self):
        text = "Ouyang Xiu and Sima Guang are historical figures."
        redacted = self.redactor.redact(text)
        self.assertTrue("[NAME]" in redacted)
        self.assertFalse("Ouyang Xiu" in redacted)
        self.assertFalse("Sima Guang" in redacted)

    def test_phone_international(self):
        cases = [
            ("Call +1-555-555-0199 now", "[Phone]"), # Valid length
            ("Mobile 13800138000 is valid", "[Phone]"),
            ("HK number 852 9123 4567", "[Phone]"),
            ("UK +44 7911 123456", "[Phone]")
        ]
        for original, tag in cases:
            redacted = self.redactor.redact(original)
            self.assertIn(tag, redacted)
            # Ensure digits are gone
            self.assertFalse(any(char.isdigit() for char in redacted.split(tag)[0]))

    def test_pnr_basic(self):
        text = "My PNR is X9Y8Z7."
        redacted = self.redactor.redact(text)
        self.assertIn("[PNR]", redacted)
        self.assertFalse("X9Y8Z7" in redacted)

    def test_pnr_false_positives(self):
        # Words that look like PNRs (6 chars, uppercase) but are dictionary words
        text = "The FLIGHT was delayed. Please TICKET me."
        redacted = self.redactor.redact(text)
        # Should NOT redact FLIGHT or TICKET
        self.assertIn("FLIGHT", redacted)
        self.assertIn("TICKET", redacted)
        self.assertNotIn("[PNR]", redacted)

    def test_pnr_context_validation(self):
        # All-alpha PNR requires context
        text = "Booking ref ABCDEF."
        redacted = self.redactor.redact(text)
        self.assertIn("[PNR]", redacted)
        self.assertFalse("ABCDEF" in redacted)

        # All-alpha without context might be skipped (depending on strictness)
        text = "Is ABCDEF a code?"
        redacted = self.redactor.redact(text)
        # If strict, this might NOT be redacted. Let's see behavior.
        # Ideally we want to avoid false positives on random acronyms.
        pass 

    def test_flight_numbers(self):
        cases = [
            ("Flight MU567 is boarding", "[Flight no]"),
            ("Code AA1234 departs soon", "[Flight no]"),
        ]
        for original, tag in cases:
            redacted = self.redactor.redact(original)
            self.assertIn(tag, redacted)

    def test_flight_number_false_positives(self):
        # "is 123" should not be a flight number
        text = "The price is 123 dollars."
        redacted = self.redactor.redact(text)
        self.assertNotIn("[Flight no]", redacted)
        self.assertIn("123", redacted) # Or some other handling, but not Flight No

    def test_ticket_numbers(self):
        # 13 digits
        text = "Ticket 1761234567890 is confirmed."
        redacted = self.redactor.redact(text)
        self.assertIn("[Ticket no]", redacted)
        self.assertFalse("1761234567890" in redacted)

        # With hyphen
        text = "Ticket 176-1234567890 is confirmed."
        redacted = self.redactor.redact(text)
        self.assertIn("[Ticket no]", redacted)
        self.assertFalse("1234567890" in redacted)

    def test_frequent_flyer(self):
        text = "Member AA12345678 has miles."
        redacted = self.redactor.redact(text)
        self.assertIn("[Frequent Flyer]", redacted)
        self.assertFalse("AA12345678" in redacted)

    def test_dob_vs_flight_date(self):
        # DOB (Past)
        text = "Born on 1990-05-20."
        redacted = self.redactor.redact(text)
        self.assertIn("[DOB]", redacted)
        
        # Flight Date (Future/Recent)
        text = "Flying on 2025-12-25."
        redacted = self.redactor.redact(text)
        self.assertNotIn("[DOB]", redacted)
        self.assertIn("2025-12-25", redacted)

    def test_email(self):
        text = "Contact me at test.user@airline.com."
        redacted = self.redactor.redact(text)
        self.assertIn("[Email]", redacted)
        self.assertFalse("test.user@airline.com" in redacted)

    def test_ids(self):
        # Credit Card (Luhn check usually, or just 16 digits)
        text = "Card 4111 1111 1111 1111"
        redacted = self.redactor.redact(text)
        self.assertIn("[Payment]", redacted)

if __name__ == '__main__':
    unittest.main()
