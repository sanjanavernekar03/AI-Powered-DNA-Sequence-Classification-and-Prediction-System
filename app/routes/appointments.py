import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, g, jsonify
from app.routes.auth import login_required
from app.services.hospital_service import get_hospital_by_id, get_doctors_by_hospital_id, get_doctor_by_id
from app.services.booking_service import create_appointment, get_user_appointments, cancel_user_appointment
from app.database.connection import get_db

appointments_bp = Blueprint('appointments', __name__, url_prefix='/appointments')


@appointments_bp.route('/api/doctor-availability', methods=['GET'])
@login_required
def doctor_availability_api():
    """Returns real-time doctor availability, weekday slots, booked slots, and best slot recommendation."""
    doctor_id = request.args.get('doctor_id', type=int)
    date_str = (request.args.get('date') or '').strip()

    if not doctor_id:
        return jsonify({'success': False, 'error': 'doctor_id is required'}), 400

    doctor = get_doctor_by_id(doctor_id)
    if not doctor:
        return jsonify({'success': False, 'error': 'Doctor not found'}), 404

    target_date = None
    if date_str:
        for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"):
            try:
                target_date = datetime.datetime.strptime(date_str, fmt).date()
                break
            except ValueError:
                pass
        if not target_date:
            return jsonify({'success': False, 'error': 'Invalid date format. Please select a valid date from the calendar.'}), 400
        if target_date < datetime.date.today():
            return jsonify({'success': False, 'error': 'Selected date cannot be in the past.'}), 400

    schedule = doctor.get('schedule') or {}
    work_days = list(schedule.keys())

    if not target_date:
        # Pick the earliest upcoming working day (starting tomorrow or today)
        curr = datetime.date.today()
        for _ in range(14):
            day_name = curr.strftime("%A")
            if day_name in work_days and schedule.get(day_name):
                target_date = curr
                break
            curr += datetime.timedelta(days=1)
        if not target_date:
            target_date = datetime.date.today() + datetime.timedelta(days=1)

    target_weekday = target_date.strftime("%A")
    is_available_day = target_weekday in schedule and bool(schedule[target_weekday])
    day_slots = schedule.get(target_weekday, []) if is_available_day else []

    # Query already-booked slots for this doctor on this date from MySQL
    booked_times = set()
    with get_db() as conn:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT appointment_time FROM appointments WHERE doctor_id = %s AND appointment_date = %s AND status != 'Cancelled'",
            (doctor_id, target_date)
        )
        for row in cur.fetchall():
            booked_times.add(row['appointment_time'].strip())
        cur.close()

    available_slots = [s for s in day_slots if s not in booked_times]

    recommended_slot = None
    if available_slots:
        recommended_slot = {
            "slot": available_slots[0],
            "day": target_weekday,
            "date": target_date.strftime("%d %B %Y"),
            "display": f"{target_weekday}, {available_slots[0]}",
            "reason": f"This is the earliest available slot with {doctor['full_name']} on {target_weekday}."
        }

    formatted_fee = f"₹{doctor['consultation_fee']} per visit" if doctor.get('consultation_fee') is not None else "Fee not available"

    return jsonify({
        'success': True,
        'doctor_id': doctor_id,
        'doctor_name': doctor['full_name'],
        'specialty': doctor['specialty'],
        'qualification': doctor.get('qualification_short') or doctor.get('qualification'),
        'experience_years': doctor.get('experience_years'),
        'hospital_id': doctor['hospital_id'],
        'hospital_name': doctor.get('hospital_name'),
        'location': doctor.get('location') or f"{doctor.get('hospital_city', '')}, {doctor.get('hospital_state', '')}".strip(', '),
        'consultation_fee': doctor.get('consultation_fee'),
        'formatted_fee': formatted_fee,
        'availability_days': doctor.get('availability_days') or ', '.join(work_days),
        'availability_time': doctor.get('availability_time') or "09:00 AM – 01:00 PM",
        'date': target_date.strftime("%Y-%m-%d"),
        'formatted_date': target_date.strftime("%A, %d %B %Y"),
        'weekday': target_weekday,
        'is_day_available': is_available_day,
        'all_day_slots': day_slots,
        'booked_slots': list(booked_times),
        'available_slots': available_slots,
        'recommended_slot': recommended_slot,
        'working_days': work_days,
        'schedule': schedule
    })


@appointments_bp.route('/book', methods=['GET', 'POST'])
@login_required
def book():
    user_id = session['user_id']
    user = g.user or {}

    hospital_id = request.args.get('hospital_id', type=int) or request.form.get('hospital_id', type=int)
    doctor_id = request.args.get('doctor_id', type=int) or request.form.get('doctor_id', type=int)

    doctor = None
    if doctor_id:
        doctor = get_doctor_by_id(doctor_id)
        if doctor and not hospital_id:
            hospital_id = doctor.get('hospital_id')

    hospital = get_hospital_by_id(hospital_id) if hospital_id else None
    docs = []
    if hospital_id:
        docs = get_doctors_by_hospital_id(hospital_id)

    if request.method == 'POST':
        selected_hosp_id = int(request.form.get('hospital_id') or (doctor['hospital_id'] if doctor else 0))
        selected_doc_id = int(request.form.get('doctor_id') or (doctor['id'] if doctor else 0))
        appointment_date = request.form.get('appointment_date', '').strip()
        appointment_time = request.form.get('appointment_time', '').strip()
        reason_for_visit = request.form.get('reason_for_visit', '').strip()
        patient_name = request.form.get('patient_name', '').strip()
        phone = request.form.get('phone', '').strip()
        patient_email = request.form.get('patient_email', '').strip() or user.get('email', '')
        notes = request.form.get('notes', '').strip()

        result = create_appointment(
            user_id=user_id,
            hospital_id=selected_hosp_id,
            doctor_id=selected_doc_id,
            appointment_date_str=appointment_date,
            appointment_time=appointment_time,
            reason_for_visit=reason_for_visit,
            patient_name=patient_name,
            phone=phone,
            patient_email=patient_email,
            notes=notes
        )

        if result['success']:
            flash("Appointment Confirmed Successfully!", "success")
            return redirect(url_for('appointments.my_appointments'))
        else:
            flash(f"Booking Error: {result['error']}", "danger")

    return render_template(
        'appointments/booking.html',
        hospital=hospital,
        doctor=doctor,
        doctors=docs,
        user=user,
        today_str=datetime.date.today().strftime("%Y-%m-%d")
    )


@appointments_bp.route('/my-appointments')
@login_required
def my_appointments():
    user_id = session['user_id']
    appts = get_user_appointments(user_id)
    return render_template('appointments/my_appointments.html', appointments=appts)


@appointments_bp.route('/cancel/<int:appointment_id>', methods=['POST'])
@login_required
def cancel(appointment_id: int):
    user_id = session['user_id']
    success = cancel_user_appointment(appointment_id, user_id)
    if success:
        flash("Appointment has been cancelled.", "info")
    else:
        flash("Unable to cancel appointment.", "danger")
    return redirect(url_for('appointments.my_appointments'))

