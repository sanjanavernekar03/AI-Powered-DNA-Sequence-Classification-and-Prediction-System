import unittest
import datetime
from app import create_app
from app.database.connection import get_db
from app.services.booking_service import create_appointment, get_user_appointments


class TestAppointmentBooking(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()
        with get_db() as conn:
            cur = conn.cursor(dictionary=True)
            cur.execute("SELECT id, username FROM users LIMIT 1")
            user = cur.fetchone()
            self.user_id = user['id'] if user else 3
            self.username = user['username'] if user else 'test'
            cur.execute("SELECT id, hospital_id, available_slots_json FROM doctors LIMIT 1")
            doc = cur.fetchone()
            self.doctor_id = doc['id'] if doc else 1
            self.hospital_id = doc['hospital_id'] if doc else 1
            import json
            slots = json.loads(doc['available_slots_json']) if doc and doc.get('available_slots_json') else ["09:00 AM"]
            self.doctor_slot = slots[0] if slots else "09:00 AM"
            cur.execute("DELETE FROM appointments WHERE reason_for_visit IN ('Cardiology Consultation', 'First Visit', 'Duplicate Attempt')")
            conn.commit()
            cur.close()
        with self.client.session_transaction() as sess:
            sess['user_id'] = self.user_id
            sess['username'] = self.username

    def test_end_to_end_appointment_creation(self):
        """Test complete appointment creation in MySQL and retrieval in My Appointments."""
        days_ahead = 10
        while (datetime.date.today() + datetime.timedelta(days=days_ahead)).weekday() >= 5:
            days_ahead += 1
        target_date = (datetime.date.today() + datetime.timedelta(days=days_ahead)).strftime("%Y-%m-%d")
        
        # 1. HTTP POST booking request
        res = self.client.post('/appointments/book', data={
            'hospital_id': self.hospital_id,
            'doctor_id': self.doctor_id,
            'appointment_date': target_date,
            'appointment_time': self.doctor_slot,
            'reason_for_visit': 'Cardiology Consultation',
            'patient_name': 'Raju Patient',
            'phone': '9876543210',
            'patient_email': 'raju2@gmail.com',
            'notes': 'Unit test appointment booking'
        }, follow_redirects=True)

        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Appointment Confirmed Successfully", res.data)
        self.assertIn(b"My Appointments", res.data)
        self.assertIn(b"Cardiology Consultation", res.data)

        # 2. Database verification directly in MySQL
        with get_db() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                "SELECT * FROM appointments WHERE user_id = %s AND reason_for_visit = %s ORDER BY id DESC LIMIT 1",
                (self.user_id, 'Cardiology Consultation')
            )
            record = cursor.fetchone()
            cursor.close()

        self.assertIsNotNone(record)
        self.assertEqual(record['patient_name'], 'Raju Patient')
        self.assertEqual(record['patient_email'], 'raju2@gmail.com')
        self.assertEqual(record['status'], 'Confirmed')

    def test_duplicate_slot_validation(self):
        """Test duplicate doctor/slot booking returns friendly error."""
        days_ahead = 15
        while (datetime.date.today() + datetime.timedelta(days=days_ahead)).weekday() >= 6:
            days_ahead += 1
        target_date = (datetime.date.today() + datetime.timedelta(days=days_ahead)).strftime("%Y-%m-%d")
        
        res1 = create_appointment(
            user_id=self.user_id, hospital_id=self.hospital_id, doctor_id=self.doctor_id,
            appointment_date_str=target_date, appointment_time='02:00 PM',
            reason_for_visit='First Visit', patient_name='Raju', phone='9876543210'
        )
        self.assertTrue(res1['success'])

        # Duplicate slot booking attempt
        res2 = create_appointment(
            user_id=self.user_id, hospital_id=self.hospital_id, doctor_id=self.doctor_id,
            appointment_date_str=target_date, appointment_time='02:00 PM',
            reason_for_visit='Duplicate Attempt', patient_name='Raju', phone='9876543210'
        )
        self.assertFalse(res2['success'])
        self.assertIn('already booked', res2['error'])


if __name__ == '__main__':
    unittest.main()
