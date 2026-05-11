import json
from datetime import datetime, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from .forms import AppointmentForm, BookingConfigForm, PatientForm, PaymentForm
from .models import Appointment, BookingConfig, BookingRequest, Patient, Payment


def money_sum(queryset):
    return queryset.aggregate(total=Sum('amount'))['total'] or 0


def get_booking_config():
    config = BookingConfig.objects.first()
    if not config:
        config = BookingConfig.objects.create()
    return config


def split_slots(value):
    return [slot.strip() for slot in value.split(',') if slot.strip()] if value else []


def normalize_time_slot(value):
    try:
        time_obj = datetime.strptime(value.strip(), '%H:%M').time()
        return f'{time_obj.hour}:{time_obj.minute:02d}'
    except (AttributeError, ValueError):
        return value


def booking_visit_type_to_appointment(value):
    visit_type_map = {
        'new_patient': Appointment.VISIT_TYPE_NEW,
        'new': Appointment.VISIT_TYPE_NEW,
        'followup': Appointment.VISIT_TYPE_FOLLOWUP,
        'follow_up': Appointment.VISIT_TYPE_FOLLOWUP,
        'annual_exam': Appointment.VISIT_TYPE_ANNUAL,
        'annual': Appointment.VISIT_TYPE_ANNUAL,
        'urgent': Appointment.VISIT_TYPE_URGENT,
        'telemedicine': Appointment.VISIT_TYPE_TELEMEDICINE,
    }
    return visit_type_map.get(value, value)


def start_of_week(day):
    return day - timedelta(days=day.weekday())


def api_booking_config(request):
    """GET - Returns booking configuration for the external website."""
    if request.method != 'GET':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    config = get_booking_config()
    data = {
        'booking_enabled': config.booking_enabled,
        'offline_message': config.offline_message,
        'clinic_name': config.clinic_name,
        'welcome_message': config.welcome_message,
        'welcome_message_es': config.welcome_message_es,
        'accepting_new_patients': config.accepting_new_patients,
        'require_phone': config.require_phone,
        'require_email': config.require_email,
        'min_days_ahead': config.min_days_ahead,
        'max_days_ahead': config.max_days_ahead,
        'visit_types': {
            'new_patient': config.show_new_patient,
            'followup': config.show_followup,
            'annual_exam': config.show_annual_exam,
            'urgent': config.show_urgent,
            'telemedicine': config.show_telemedicine,
        },
        'available_slots': {
            'monday': split_slots(config.available_slots_monday),
            'tuesday': split_slots(config.available_slots_tuesday),
            'wednesday': split_slots(config.available_slots_wednesday),
            'thursday': split_slots(config.available_slots_thursday),
            'friday': split_slots(config.available_slots_friday),
            'saturday': split_slots(config.available_slots_saturday),
            'sunday': [],
        },
    }
    return JsonResponse(data)


@csrf_exempt
def api_book_appointment(request):
    """POST - Receives booking request from external website."""
    if request.method == 'OPTIONS':
        return JsonResponse({})
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    try:
        config = get_booking_config()
        if not config.booking_enabled:
            return JsonResponse(
                {'success': False, 'error': config.offline_message},
                status=403,
            )

        data = json.loads(request.body or '{}')
        required = ['first_name', 'last_name', 'requested_date', 'requested_time', 'visit_type']
        if config.require_phone:
            required.append('phone')
        if config.require_email:
            required.append('email')

        for field in required:
            if not data.get(field):
                return JsonResponse(
                    {'success': False, 'error': f'Field {field} is required'},
                    status=400,
                )

        booking = BookingRequest.objects.create(
            first_name=data.get('first_name'),
            last_name=data.get('last_name'),
            phone=data.get('phone', ''),
            email=data.get('email', ''),
            date_of_birth=data.get('date_of_birth') or None,
            language=data.get('language', 'es'),
            is_new_patient=data.get('is_new_patient', True),
            requested_date=data.get('requested_date'),
            requested_time=normalize_time_slot(data.get('requested_time')),
            visit_type=data.get('visit_type'),
            notes=data.get('notes', ''),
            ip_address=request.META.get('REMOTE_ADDR'),
        )

        return JsonResponse(
            {
                'success': True,
                'message': 'Booking request received successfully',
                'booking_id': booking.id,
            },
            status=201,
        )

    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON body'}, status=400)
    except Exception as exc:
        return JsonResponse({'success': False, 'error': str(exc)}, status=500)


def api_available_slots(request):
    """GET - Returns available slots for a specific date."""
    if request.method != 'GET':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    date_str = request.GET.get('date')
    if not date_str:
        return JsonResponse({'error': 'date parameter required'}, status=400)

    try:
        requested_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        return JsonResponse({'error': 'Invalid date format. Use YYYY-MM-DD'}, status=400)

    config = get_booking_config()
    day_name = requested_date.strftime('%A').lower()
    slots_str = getattr(config, f'available_slots_{day_name}', '')
    all_slots = split_slots(slots_str)

    booked = Appointment.objects.filter(date=requested_date).values_list('time', flat=True)
    booked_times = [f'{time_obj.hour}:{time_obj.minute:02d}' for time_obj in booked]
    pending_bookings = BookingRequest.objects.filter(
        requested_date=requested_date,
        status='pending',
    ).values_list('requested_time', flat=True)

    unavailable = set(booked_times) | {normalize_time_slot(slot) for slot in pending_bookings}
    available = [slot for slot in all_slots if normalize_time_slot(slot) not in unavailable]

    return JsonResponse(
        {
            'date': date_str,
            'day': day_name,
            'available_slots': available,
            'total_slots': len(all_slots),
            'booked_slots': len(unavailable),
        }
    )


@login_required
def dashboard_view(request):
    today = timezone.localdate()
    month_payments = Payment.objects.filter(date__year=today.year, date__month=today.month)
    today_appointments = Appointment.objects.select_related('patient').filter(date=today).order_by('time')
    context = {
        'total_patients': Patient.objects.count(),
        'today_appointments_count': today_appointments.count(),
        'pending_appointments_count': Appointment.objects.filter(status=Appointment.STATUS_PENDING).count(),
        'month_payments_total': money_sum(month_payments),
        'recent_patients': Patient.objects.order_by('-created_at')[:5],
        'today_appointments': today_appointments,
    }
    return render(request, 'patients/dashboard.html', context)


@login_required
def patient_list_view(request):
    patients = Patient.objects.order_by('last_name', 'first_name')
    q = request.GET.get('q', '').strip()
    status = request.GET.get('status', '')
    payment_type = request.GET.get('payment_type', '')
    language = request.GET.get('language', '')

    if q:
        patients = patients.filter(
            Q(first_name__icontains=q)
            | Q(last_name__icontains=q)
            | Q(phone__icontains=q)
            | Q(email__icontains=q)
        )
    if status == 'active':
        patients = patients.filter(is_active=True)
    elif status == 'inactive':
        patients = patients.filter(is_active=False)
    if payment_type:
        patients = patients.filter(payment_type=payment_type)
    if language:
        patients = patients.filter(language=language)

    page_obj = Paginator(patients, 10).get_page(request.GET.get('page'))
    return render(
        request,
        'patients/patient_list.html',
        {'page_obj': page_obj, 'filters': {'q': q, 'status': status, 'payment_type': payment_type, 'language': language}},
    )


@login_required
def patient_create_view(request):
    form = PatientForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        form.save()
        return redirect('patient_list')
    return render(request, 'patients/patient_form.html', {'form': form, 'form_title': 'New Patient'})


@login_required
def patient_update_view(request, pk):
    patient = get_object_or_404(Patient, pk=pk)
    form = PatientForm(request.POST or None, instance=patient)
    if request.method == 'POST' and form.is_valid():
        form.save()
        return redirect('patient_list')
    return render(request, 'patients/patient_form.html', {'form': form, 'form_title': 'Edit Patient'})


@login_required
def appointment_list_view(request):
    appointments = Appointment.objects.select_related('patient').order_by('date', 'time')
    date = request.GET.get('date', '')
    status = request.GET.get('status', '')
    visit_type = request.GET.get('visit_type', '')
    if date:
        appointments = appointments.filter(date=date)
    if status:
        appointments = appointments.filter(status=status)
    if visit_type:
        appointments = appointments.filter(visit_type=visit_type)
    return render(
        request,
        'patients/appointment_list.html',
        {
            'appointments': appointments,
            'filters': {'date': date, 'status': status, 'visit_type': visit_type},
            'status_choices': Appointment.STATUS_CHOICES,
            'visit_type_choices': Appointment.VISIT_TYPE_CHOICES,
        },
    )


@login_required
def appointment_create_view(request):
    form = AppointmentForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        form.save()
        return redirect('appointment_list')
    return render(request, 'patients/appointment_form.html', {'form': form, 'form_title': 'New Appointment'})


@login_required
def appointment_update_view(request, pk):
    appointment = get_object_or_404(Appointment, pk=pk)
    form = AppointmentForm(request.POST or None, instance=appointment)
    if request.method == 'POST' and form.is_valid():
        form.save()
        return redirect('appointment_list')
    return render(request, 'patients/appointment_form.html', {'form': form, 'form_title': 'Edit Appointment'})


@login_required
def payment_list_view(request):
    today = timezone.localdate()
    payments = Payment.objects.select_related('patient', 'appointment').order_by('-date', '-id')
    month_payments = payments.filter(date__year=today.year, date__month=today.month)
    return render(
        request,
        'patients/payment_list.html',
        {
            'payments': payments,
            'month_total': money_sum(month_payments),
            'all_time_total': money_sum(Payment.objects.all()),
            'month_transaction_count': month_payments.count(),
        },
    )


@login_required
def payment_create_view(request):
    form = PaymentForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        form.save()
        return redirect('payment_list')
    return render(request, 'patients/payment_form.html', {'form': form, 'form_title': 'New Payment'})


@login_required
def payment_update_view(request, pk):
    payment = get_object_or_404(Payment, pk=pk)
    form = PaymentForm(request.POST or None, instance=payment)
    if request.method == 'POST' and form.is_valid():
        form.save()
        return redirect('payment_list')
    return render(request, 'patients/payment_form.html', {'form': form, 'form_title': 'Edit Payment'})


@login_required
def booking_requests_view(request):
    view_mode = request.GET.get('view', 'list')
    bookings = BookingRequest.objects.all().order_by('-created_at')
    status_filter = request.GET.get('status', '')
    if status_filter:
        bookings = bookings.filter(status=status_filter)

    week_value = request.GET.get('week', '')
    try:
        selected_day = datetime.strptime(week_value, '%Y-%m-%d').date() if week_value else timezone.localdate()
    except ValueError:
        selected_day = timezone.localdate()
    week_start = start_of_week(selected_day)
    week_days = [week_start + timedelta(days=offset) for offset in range(7)]
    week_end = week_days[-1]
    appointments = Appointment.objects.select_related('patient').filter(
        date__range=(week_start, week_end),
    ).order_by('date', 'time')
    pending_week_bookings = BookingRequest.objects.filter(
        requested_date__range=(week_start, week_end),
        status='pending',
    ).order_by('requested_date', 'requested_time')

    calendar_days = []
    for day in week_days:
        calendar_days.append(
            {
                'date': day,
                'appointments': [appointment for appointment in appointments if appointment.date == day],
                'bookings': [booking for booking in pending_week_bookings if booking.requested_date == day],
            }
        )

    context = {
        'bookings': bookings,
        'pending_count': BookingRequest.objects.filter(status='pending').count(),
        'status_filter': status_filter,
        'view_mode': view_mode,
        'calendar_days': calendar_days,
        'week_start': week_start,
        'week_end': week_end,
        'previous_week': week_start - timedelta(days=7),
        'next_week': week_start + timedelta(days=7),
    }
    return render(request, 'patients/booking_requests.html', context)


@login_required
def booking_confirm_view(request, pk):
    """Convert a booking request into a real appointment."""
    booking = get_object_or_404(BookingRequest, pk=pk)
    existing_patient = Patient.objects.filter(phone=booking.phone).first()

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'confirm':
            patient = existing_patient
            if not patient:
                patient = Patient.objects.create(
                    first_name=booking.first_name,
                    last_name=booking.last_name,
                    date_of_birth=booking.date_of_birth,
                    phone=booking.phone,
                    email=booking.email,
                    language=booking.language,
                )

            time_obj = datetime.strptime(booking.requested_time, '%H:%M').time()
            appointment = Appointment.objects.create(
                patient=patient,
                date=booking.requested_date,
                time=time_obj,
                visit_type=booking_visit_type_to_appointment(booking.visit_type),
                status=Appointment.STATUS_CONFIRMED,
                notes=booking.notes,
            )

            booking.status = 'converted'
            booking.converted_to_appointment = appointment
            booking.save()
            messages.success(request, 'Booking converted to an appointment.')
            return redirect('booking_requests')

        if action == 'cancel':
            booking.status = 'cancelled'
            booking.save()
            messages.success(request, 'Booking request cancelled.')
            return redirect('booking_requests')

    return render(
        request,
        'patients/booking_confirm.html',
        {'booking': booking, 'existing_patient': existing_patient},
    )


@login_required
def booking_config_view(request):
    config = get_booking_config()

    if request.method == 'POST':
        form = BookingConfigForm(request.POST, instance=config)
        if form.is_valid():
            form.save()
            messages.success(request, 'Booking configuration saved successfully.')
            return redirect('booking_config')
    else:
        form = BookingConfigForm(instance=config)

    slot_fields = [
        ('Monday', form['available_slots_monday'], split_slots(config.available_slots_monday)),
        ('Tuesday', form['available_slots_tuesday'], split_slots(config.available_slots_tuesday)),
        ('Wednesday', form['available_slots_wednesday'], split_slots(config.available_slots_wednesday)),
        ('Thursday', form['available_slots_thursday'], split_slots(config.available_slots_thursday)),
        ('Friday', form['available_slots_friday'], split_slots(config.available_slots_friday)),
        ('Saturday', form['available_slots_saturday'], split_slots(config.available_slots_saturday)),
    ]

    return render(
        request,
        'patients/booking_config.html',
        {
            'form': form,
            'config': config,
            'slot_fields': slot_fields,
            'api_url': request.build_absolute_uri('/api/book-appointment/'),
            'config_url': request.build_absolute_uri('/api/booking-config/'),
            'slots_url': request.build_absolute_uri('/api/available-slots/?date=YYYY-MM-DD'),
        },
    )
