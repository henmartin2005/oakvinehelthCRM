import calendar
import json
from datetime import date, datetime, timedelta

from django.contrib import messages
from django.contrib.auth import get_user_model, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group
from django.core.paginator import Paginator
from django.db.models import Q, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from .forms import (
    AppointmentForm,
    BookingConfigForm,
    CRMPasswordChangeForm,
    CRMSetPasswordForm,
    CRMUserCreationForm,
    CRMUserUpdateForm,
    PatientForm,
    PaymentForm,
    ROLE_ADMIN,
    ROLE_ASSISTANT,
    ROLE_USER,
    UserPasswordTargetForm,
)
from .models import Appointment, BookingConfig, BookingLog, BookingRequest, Patient, PatientActivity, Payment


def money_sum(queryset):
    return queryset.aggregate(total=Sum('amount'))['total'] or 0


def ensure_crm_roles():
    groups = {}
    for role in [ROLE_ADMIN, ROLE_ASSISTANT, ROLE_USER]:
        groups[role], _ = Group.objects.get_or_create(name=role)
    return groups


def user_has_role(user, role):
    return user.is_authenticated and user.groups.filter(name=role).exists()


def is_crm_admin(user):
    return user.is_authenticated and (user.is_superuser or user_has_role(user, ROLE_ADMIN))


def is_crm_assistant(user):
    return user_has_role(user, ROLE_ASSISTANT)


def get_user_role(user):
    if user.is_superuser or user_has_role(user, ROLE_ADMIN):
        return ROLE_ADMIN
    if user_has_role(user, ROLE_ASSISTANT):
        return ROLE_ASSISTANT
    if user_has_role(user, ROLE_USER):
        return ROLE_USER
    return ROLE_USER


def assign_user_role(user, role):
    groups = ensure_crm_roles()
    user.groups.remove(*groups.values())
    user.groups.add(groups[role])
    user.is_staff = role == ROLE_ADMIN
    user.save()


def disable_form_fields(form):
    for field in form.fields.values():
        field.disabled = True
    return form


def crm_admin_count():
    return get_user_model().objects.filter(Q(is_superuser=True) | Q(groups__name=ROLE_ADMIN)).distinct().count()


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


def find_existing_patient(phone='', email=''):
    patient = None
    if phone:
        patient = Patient.objects.filter(phone=phone).first()
    if not patient and email:
        patient = Patient.objects.filter(email=email).first()
    return patient


def create_or_update_patient_from_booking(data):
    phone = data.get('phone', '')
    email = data.get('email', '')
    patient = find_existing_patient(phone=phone, email=email)

    if not patient:
        return Patient.objects.create(
            first_name=data.get('first_name', ''),
            last_name=data.get('last_name', ''),
            date_of_birth=data.get('date_of_birth') or None,
            phone=phone,
            email=email,
            language=data.get('language', Patient.LANGUAGE_SPANISH),
            payment_type=Patient.PAYMENT_CASH,
        )

    changed = False
    for field in ['first_name', 'last_name', 'phone', 'email', 'language']:
        value = data.get(field)
        if value and not getattr(patient, field):
            setattr(patient, field, value)
            changed = True
    if data.get('date_of_birth') and not patient.date_of_birth:
        patient.date_of_birth = data.get('date_of_birth')
        changed = True
    if changed:
        patient.save()
    return patient


def booking_patient_initial(booking):
    return {
        'first_name': booking.first_name,
        'last_name': booking.last_name,
        'date_of_birth': booking.date_of_birth,
        'phone': booking.phone,
        'email': booking.email,
        'language': booking.language,
        'payment_type': Patient.PAYMENT_CASH,
        'is_active': True,
    }


def booking_user_name(user):
    full_name = user.get_full_name().strip()
    return full_name or user.get_username()


def log_booking_event(booking, action, user=None, log_type=BookingLog.LOG_SYSTEM, details=None, created_at=None):
    log_data = {
        'booking': booking,
        'action': action,
        'log_type': log_type,
        'details': details or {},
    }
    if user and user.is_authenticated:
        log_data['user_id'] = str(user.pk)
        log_data['user_name'] = booking_user_name(user)
    if created_at:
        log_data['created_at'] = created_at
    return BookingLog.objects.create(**log_data)


def ensure_booking_default_logs(booking, existing_patient=None):
    BookingLog.objects.get_or_create(
        booking=booking,
        action='Booking request received',
        defaults={
            'log_type': BookingLog.LOG_SYSTEM,
            'created_at': booking.created_at,
            'details': {'source': 'online_booking'},
        },
    )
    if existing_patient:
        BookingLog.objects.get_or_create(
            booking=booking,
            action='Duplicate phone detected',
            defaults={
                'log_type': BookingLog.LOG_WARNING,
                'details': {
                    'patient_id': existing_patient.patient_code,
                    'patient_name': f'{existing_patient.first_name} {existing_patient.last_name}',
                    'phone': booking.phone,
                },
            },
        )


def attach_patients_to_bookings(bookings):
    phones = {booking.phone for booking in bookings if booking.phone}
    emails = {booking.email for booking in bookings if booking.email}
    patients = Patient.objects.filter(Q(phone__in=phones) | Q(email__in=emails)).order_by('id')
    patients_by_phone = {patient.phone: patient for patient in patients if patient.phone}
    patients_by_email = {patient.email: patient for patient in patients if patient.email}

    for booking in bookings:
        booking.matched_patient = patients_by_phone.get(booking.phone) or patients_by_email.get(booking.email)
    return bookings


def build_booking_calendar(view_mode, selected_day):
    if view_mode == 'day':
        period_start = selected_day
        period_end = selected_day
        days = [selected_day]
        previous_period = selected_day - timedelta(days=1)
        next_period = selected_day + timedelta(days=1)
        period_label = selected_day.strftime('%B %d, %Y')
        calendar_class = 'calendar-grid calendar-day-grid'
    elif view_mode == 'month':
        current_monday = start_of_week(selected_day)
        period_start = current_monday - timedelta(weeks=1)
        days = [period_start + timedelta(days=offset) for offset in range(28)]
        period_end = days[-1]
        previous_period = period_start - timedelta(weeks=4)
        next_period = period_start + timedelta(weeks=4)
        period_label = f'{period_start.strftime("%b %d")} - {period_end.strftime("%b %d, %Y")}'
        calendar_class = 'cal-grid'
    else:
        period_start = start_of_week(selected_day)
        days = [period_start + timedelta(days=offset) for offset in range(7)]
        period_end = days[-1]
        previous_period = period_start - timedelta(days=7)
        next_period = period_start + timedelta(days=7)
        period_label = f'{period_start.strftime("%b %d")} - {period_end.strftime("%b %d, %Y")}'
        calendar_class = 'calendar-grid'

    appointments = Appointment.objects.select_related('patient').filter(
        date__range=(period_start, period_end),
    ).order_by('date', 'time')
    pending_bookings = BookingRequest.objects.filter(
        requested_date__range=(period_start, period_end),
        status='pending',
    ).order_by('requested_date', 'requested_time')
    pending_bookings = attach_patients_to_bookings(list(pending_bookings))

    calendar_days = []
    for day in days:
        calendar_days.append(
            {
                'date': day,
                'is_current_month': day.month == selected_day.month,
                'appointments': [appointment for appointment in appointments if appointment.date == day],
                'bookings': [booking for booking in pending_bookings if booking.requested_date == day],
            }
        )
    calendar_weeks = [calendar_days[index:index + 7] for index in range(0, len(calendar_days), 7)]

    return {
        'calendar_days': calendar_days,
        'calendar_weeks': calendar_weeks,
        'period_start': period_start,
        'period_end': period_end,
        'previous_period': previous_period,
        'next_period': next_period,
        'period_label': period_label,
        'calendar_class': calendar_class,
    }


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

        patient = create_or_update_patient_from_booking(data)
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
                'patient_id': patient.id,
                'patient_code': patient.patient_code,
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
    today_appointments = Appointment.objects.select_related('patient').filter(date=today).order_by('time')
    context = {
        'total_patients': Patient.objects.count(),
        'today_appointments_count': today_appointments.count(),
        'pending_appointments_count': Appointment.objects.filter(status=Appointment.STATUS_PENDING).count(),
        'recent_patients': Patient.objects.order_by('-created_at')[:5],
        'today_appointments': today_appointments,
    }
    if request.user.is_superuser:
        context['recent_logs'] = BookingLog.objects.select_related('booking').order_by('-created_at')[:15]
    else:
        context['recent_logs'] = []
    return render(request, 'patients/dashboard.html', context)


@login_required
def admin_profile_view(request):
    ensure_crm_roles()
    target_user = request.user
    can_manage_users = is_crm_admin(request.user)
    can_change_own_password = not is_crm_assistant(request.user)
    own_password_form = CRMPasswordChangeForm(request.user, prefix='own') if can_change_own_password else None
    target_form = UserPasswordTargetForm(prefix='target')
    reset_password_form = CRMSetPasswordForm(target_user, prefix='reset')
    create_user_form = CRMUserCreationForm(prefix='create')

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'change_own_password':
            if not can_change_own_password:
                messages.error(request, 'Assistant users cannot change their system password.')
                return redirect('admin_profile')
            own_password_form = CRMPasswordChangeForm(request.user, request.POST, prefix='own')
            if own_password_form.is_valid():
                user = own_password_form.save()
                update_session_auth_hash(request, user)
                messages.success(request, 'Your password was updated successfully.')
                return redirect('admin_profile')

        if action == 'reset_user_password':
            if not can_manage_users:
                messages.error(request, 'Only admins can change passwords for other users.')
                return redirect('admin_profile')

            target_form = UserPasswordTargetForm(request.POST, prefix='target')
            if target_form.is_valid():
                target_user = target_form.cleaned_data['user']
                reset_password_form = CRMSetPasswordForm(target_user, request.POST, prefix='reset')
                if reset_password_form.is_valid():
                    reset_password_form.save()
                    messages.success(request, f'Password updated for {target_user.username}.')
                    return redirect('admin_profile')
            else:
                reset_password_form = CRMSetPasswordForm(target_user, request.POST, prefix='reset')

        if action == 'create_user':
            if not can_manage_users:
                messages.error(request, 'Only admins can create CRM users.')
                return redirect('admin_profile')

            create_user_form = CRMUserCreationForm(request.POST, prefix='create')
            if create_user_form.is_valid():
                user = create_user_form.save(commit=False)
                role = create_user_form.cleaned_data['role']
                user.is_staff = role == ROLE_ADMIN
                user.save()
                assign_user_role(user, role)
                messages.success(request, f'User {user.username} was created as {role}.')
                return redirect('admin_profile')

    users = get_user_model().objects.order_by('username') if can_manage_users else []
    for user in users:
        user.crm_role = get_user_role(user)
    return render(
        request,
        'patients/admin_profile.html',
        {
            'own_password_form': own_password_form,
            'target_form': target_form,
            'reset_password_form': reset_password_form,
            'create_user_form': create_user_form,
            'users': users,
            'can_manage_users': can_manage_users,
            'can_change_own_password': can_change_own_password,
        },
    )


@login_required
def user_update_view(request, pk):
    ensure_crm_roles()
    if not is_crm_admin(request.user):
        messages.error(request, 'Only admins can modify CRM users.')
        return redirect('admin_profile')

    user = get_object_or_404(get_user_model(), pk=pk)
    original_is_admin = is_crm_admin(user)
    form = CRMUserUpdateForm(request.POST or None, instance=user)

    if request.method == 'POST' and form.is_valid():
        updated_user = form.save(commit=False)
        role = form.cleaned_data['role']
        if original_is_admin and role != ROLE_ADMIN and crm_admin_count() <= 1:
            form.add_error('role', 'At least one admin must remain in the CRM.')
        else:
            updated_user.is_staff = role == ROLE_ADMIN
            if role == ROLE_ADMIN and user.is_superuser:
                updated_user.is_staff = True
            updated_user.save()
            assign_user_role(updated_user, role)
            messages.success(request, f'User {updated_user.username} was updated.')
            return redirect('admin_profile')

    return render(
        request,
        'patients/user_form.html',
        {
            'form': form,
            'managed_user': user,
            'form_title': f'Edit User: {user.username}',
        },
    )


@login_required
def user_delete_view(request, pk):
    ensure_crm_roles()
    if not is_crm_admin(request.user):
        messages.error(request, 'Only admins can delete CRM users.')
        return redirect('admin_profile')

    user = get_object_or_404(get_user_model(), pk=pk)
    if user == request.user:
        messages.error(request, 'You cannot delete your own user account.')
        return redirect('admin_profile')
    if is_crm_admin(user) and crm_admin_count() <= 1:
        messages.error(request, 'At least one admin must remain in the CRM.')
        return redirect('admin_profile')

    if request.method == 'POST':
        username = user.username
        user.delete()
        messages.success(request, f'User {username} was deleted.')
        return redirect('admin_profile')

    user.crm_role = get_user_role(user)
    return render(request, 'patients/user_confirm_delete.html', {'managed_user': user})


@login_required
def patient_list_view(request):
    patients = Patient.objects.order_by('last_name', 'first_name')
    q = request.GET.get('q', '').strip()
    status = request.GET.get('status', '')
    language = request.GET.get('language', '')

    if q:
        patients = patients.filter(
            Q(first_name__icontains=q)
            | Q(last_name__icontains=q)
            | Q(phone__icontains=q)
            | Q(email__icontains=q)
        )
        if q.isdigit():
            patients = patients | Patient.objects.filter(id=int(q)) | Patient.objects.filter(id=int(q) + 1)
    if status == 'active':
        patients = patients.filter(is_active=True)
    elif status == 'inactive':
        patients = patients.filter(is_active=False)
    if language:
        patients = patients.filter(language=language)
    patients = patients.distinct()

    page_obj = Paginator(patients, 10).get_page(request.GET.get('page'))
    return render(
        request,
        'patients/patient_list.html',
        {'page_obj': page_obj, 'filters': {'q': q, 'status': status, 'language': language}},
    )


@login_required
def patient_create_view(request):
    if is_crm_assistant(request.user):
        messages.error(request, 'Assistant users cannot create or modify patient records.')
        return redirect('patient_list')
    form = PatientForm(request.POST or None)
    form.fields.pop('payment_type', None)
    if request.method == 'POST' and form.is_valid():
        patient = form.save()
        PatientActivity.objects.create(
            patient=patient,
            activity_type=PatientActivity.TYPE_ADMIN,
            title='Patient profile created',
            user_id=str(request.user.pk),
            user_name=booking_user_name(request.user),
        )
        return redirect('patient_list')
    return render(request, 'patients/patient_form.html', {'form': form, 'form_title': 'New Patient', 'patient': None})


@login_required
def patient_update_view(request, pk):
    if is_crm_assistant(request.user):
        messages.error(request, 'Assistant users cannot create or modify patient records.')
        return redirect('patient_list')
    patient = get_object_or_404(Patient, pk=pk)
    form = PatientForm(request.POST or None, instance=patient)
    form.fields.pop('payment_type', None)
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'add_activity':
            notes = request.POST.get('activity_notes', '').strip()
            activity_type = request.POST.get('activity_type', PatientActivity.TYPE_NOTE)
            valid_types = {choice[0] for choice in PatientActivity.ACTIVITY_TYPE_CHOICES}
            if not notes:
                messages.error(request, 'Note is required.')
            else:
                PatientActivity.objects.create(
                    patient=patient,
                    activity_type=activity_type if activity_type in valid_types else PatientActivity.TYPE_NOTE,
                    title='Patient note',
                    notes=notes,
                    user_id=str(request.user.pk),
                    user_name=booking_user_name(request.user),
                )
                messages.success(request, 'Patient note saved.')
                return redirect('patient_update', pk=patient.pk)
        elif form.is_valid():
            changed_fields = list(form.changed_data)
            profile_note = form.cleaned_data.get('insurance_notes', '').strip()
            form.save()
            if 'insurance_notes' in changed_fields and profile_note:
                PatientActivity.objects.create(
                    patient=patient,
                    activity_type=PatientActivity.TYPE_NOTE,
                    title='Patient profile note added',
                    notes=profile_note,
                    user_id=str(request.user.pk),
                    user_name=booking_user_name(request.user),
                )
            if changed_fields:
                profile_fields = [field for field in changed_fields if field != 'insurance_notes']
                PatientActivity.objects.create(
                    patient=patient,
                    activity_type=PatientActivity.TYPE_ADMIN,
                    title='Patient profile updated',
                    notes=', '.join(profile_fields) if profile_fields else 'Profile notes updated',
                    user_id=str(request.user.pk),
                    user_name=booking_user_name(request.user),
                )
                messages.success(request, 'Patient profile saved.')
            else:
                messages.success(request, 'No patient changes to save.')
            return redirect('patient_update', pk=patient.pk)

    patient_appointments = Appointment.objects.filter(patient=patient).order_by('-date', '-time')[:20]
    patient_payments = Payment.objects.filter(patient=patient).order_by('-date', '-id')[:10]
    patient_activities = PatientActivity.objects.filter(patient=patient).order_by('-created_at')[:20]
    patient_notes = PatientActivity.objects.filter(patient=patient, activity_type=PatientActivity.TYPE_NOTE).order_by('-created_at')[:8]
    return render(
        request,
        'patients/patient_form.html',
        {
            'form': form,
            'form_title': 'Edit Patient',
            'patient': patient,
            'patient_appointments': patient_appointments,
            'patient_payments': patient_payments,
            'patient_activities': patient_activities,
            'patient_notes': patient_notes,
            'activity_type_choices': PatientActivity.ACTIVITY_TYPE_CHOICES,
        },
    )


@login_required
def appointment_calendar_view(request):
    today = date.today()
    days_since_monday = today.weekday()
    current_monday = today - timedelta(days=days_since_monday)
    start_date = current_monday - timedelta(weeks=1)
    end_date = start_date + timedelta(weeks=4) - timedelta(days=1)

    appointments = Appointment.objects.filter(
        date__gte=start_date,
        date__lte=end_date,
    ).select_related('patient').order_by('date', 'time')

    appt_by_date = {}
    for appt in appointments:
        key = appt.date.strftime('%Y-%m-%d')
        appt_by_date.setdefault(key, []).append(
            {
                'id': appt.id,
                'time': appt.time.strftime('%I:%M %p') if appt.time else '',
                'patient_id': appt.patient.patient_code,
                'patient_name': f'{appt.patient.first_name} {appt.patient.last_name}',
                'visit_type': appt.get_visit_type_display() if appt.visit_type else '',
                'status': appt.status or Appointment.STATUS_CONFIRMED,
            }
        )

    days = []
    current = start_date
    while current <= end_date:
        days.append(
            {
                'date': current,
                'key': current.strftime('%Y-%m-%d'),
                'day_num': current.day,
                'weekday': current.strftime('%a'),
                'is_today': current == today,
                'is_current_month': current.month == today.month,
            }
        )
        current += timedelta(days=1)

    weeks = [days[i:i + 7] for i in range(0, 28, 7)]

    return render(
        request,
        'patients/appointments_calendar.html',
        {
            'weeks': weeks,
            'appt_by_date': json.dumps(appt_by_date),
            'appt_by_date_raw': appt_by_date,
            'start_date': start_date,
            'end_date': end_date,
            'today': today,
            'current_view': 'month',
        },
    )


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
        return redirect('appointments_calendar')
    return render(request, 'patients/appointment_form.html', {'form': form, 'form_title': 'New Appointment', 'appointment': None})


@login_required
def appointment_update_view(request, pk):
    appointment = get_object_or_404(Appointment, pk=pk)
    form = AppointmentForm(request.POST or None, instance=appointment)
    if request.method == 'POST' and form.is_valid():
        form.save()
        return redirect('appointments_calendar')
    return render(request, 'patients/appointment_form.html', {'form': form, 'form_title': 'Edit Appointment', 'appointment': appointment})


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
    if view_mode == 'calendar':
        view_mode = 'week'
    bookings = BookingRequest.objects.all().order_by('-created_at')
    status_filter = request.GET.get('status', '')
    if status_filter:
        bookings = bookings.filter(status=status_filter)
    search_query = request.GET.get('q', '').strip()
    if search_query:
        patient_matches = Patient.objects.filter(
            Q(first_name__icontains=search_query)
            | Q(last_name__icontains=search_query)
            | Q(phone__icontains=search_query)
            | Q(email__icontains=search_query)
        )
        if search_query.isdigit():
            patient_code_id = int(search_query) + 1
            patient_matches = patient_matches | Patient.objects.filter(id=int(search_query))
            patient_matches = patient_matches | Patient.objects.filter(id=patient_code_id)

        matched_phones = patient_matches.exclude(phone='').values_list('phone', flat=True)
        matched_emails = patient_matches.exclude(email='').values_list('email', flat=True)
        bookings = bookings.filter(
            Q(first_name__icontains=search_query)
            | Q(last_name__icontains=search_query)
            | Q(phone__icontains=search_query)
            | Q(email__icontains=search_query)
            | Q(phone__in=matched_phones)
            | Q(email__in=matched_emails)
        ).distinct()

    bookings = attach_patients_to_bookings(list(bookings))

    date_value = request.GET.get('date') or request.GET.get('week', '')
    try:
        selected_day = datetime.strptime(date_value, '%Y-%m-%d').date() if date_value else timezone.localdate()
    except ValueError:
        selected_day = timezone.localdate()
    calendar_context = build_booking_calendar(view_mode, selected_day)

    context = {
        'bookings': bookings,
        'pending_count': BookingRequest.objects.filter(status='pending').count(),
        'status_filter': status_filter,
        'search_query': search_query,
        'view_mode': view_mode,
        'selected_day': selected_day,
    }
    context.update(calendar_context)
    return render(request, 'patients/booking_requests.html', context)


@login_required
def booking_confirm_view(request, pk):
    """Convert a booking request into a real appointment."""
    booking = get_object_or_404(BookingRequest, pk=pk)
    existing_patient = find_existing_patient(phone=booking.phone, email=booking.email)
    can_modify_patients = not is_crm_assistant(request.user)
    can_view_activity_log = request.user.is_superuser
    ensure_booking_default_logs(booking, existing_patient)
    patient_form = PatientForm(
        request.POST or None,
        instance=existing_patient,
        initial=booking_patient_initial(booking),
        prefix='patient',
    )
    patient_form.fields.pop('patient_code', None)
    patient_form.fields.pop('payment_type', None)
    patient_form.fields['insurance_notes'].widget.attrs['rows'] = 3
    if not can_modify_patients:
        disable_form_fields(patient_form)

    def render_booking_confirm():
        return render(
            request,
            'patients/booking_confirm.html',
            {
                'booking': booking,
                'existing_patient': existing_patient,
                'patient_form': patient_form,
                'can_modify_patients': can_modify_patients,
                'can_view_activity_log': can_view_activity_log,
                'booking_logs': booking.logs.all(),
            },
        )

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'save_patient' and not can_modify_patients:
            messages.error(request, 'Assistant users cannot modify patient records.')
            return redirect('booking_confirm', pk=booking.pk)

        if action == 'confirm' and not can_modify_patients:
            patient = existing_patient
            if not patient:
                patient = create_or_update_patient_from_booking(
                    {
                        'first_name': booking.first_name,
                        'last_name': booking.last_name,
                        'date_of_birth': booking.date_of_birth,
                        'phone': booking.phone,
                        'email': booking.email,
                        'language': booking.language,
                    }
                )

            time_obj = datetime.strptime(booking.requested_time, '%H:%M').time()
            appointment = Appointment.objects.create(
                patient=patient,
                date=booking.requested_date,
                time=time_obj,
                visit_type=booking_visit_type_to_appointment(booking.visit_type),
                status=Appointment.STATUS_CONFIRMED,
                notes=request.POST.get('appointment_notes', booking.notes),
            )

            booking.status = 'converted'
            booking.converted_to_appointment = appointment
            booking.save()
            log_booking_event(
                booking,
                'Status changed to Converted',
                request.user,
                BookingLog.LOG_ADMIN,
                {'appointment_id': appointment.pk},
            )
            log_booking_event(
                booking,
                'Added to calendar',
                request.user,
                BookingLog.LOG_ADMIN,
                {'appointment_id': appointment.pk},
            )
            messages.success(request, 'Booking converted to an appointment.')
            return redirect('booking_requests')

        if action in ['save_patient', 'confirm']:
            if not patient_form.is_valid():
                return render_booking_confirm()

            is_new_patient_record = not (patient_form.instance and patient_form.instance.pk)
            changed_fields = list(patient_form.changed_data)
            patient = patient_form.save()
            existing_patient = patient
            if is_new_patient_record:
                changed_fields = list(patient_form.cleaned_data.keys())

            if action == 'save_patient':
                log_booking_event(
                    booking,
                    'Patient data updated',
                    request.user,
                    BookingLog.LOG_ADMIN,
                    {'fields': changed_fields},
                )
                messages.success(request, 'Patient information saved.')
                return redirect('booking_confirm', pk=booking.pk)

            time_obj = datetime.strptime(booking.requested_time, '%H:%M').time()
            appointment = Appointment.objects.create(
                patient=patient,
                date=booking.requested_date,
                time=time_obj,
                visit_type=booking_visit_type_to_appointment(booking.visit_type),
                status=Appointment.STATUS_CONFIRMED,
                notes=request.POST.get('appointment_notes', booking.notes),
            )

            booking.status = 'converted'
            booking.converted_to_appointment = appointment
            booking.save()
            if changed_fields:
                log_booking_event(
                    booking,
                    'Patient data edited',
                    request.user,
                    BookingLog.LOG_ADMIN,
                    {'fields': changed_fields},
                )
            log_booking_event(
                booking,
                'Status changed to Converted',
                request.user,
                BookingLog.LOG_ADMIN,
                {'appointment_id': appointment.pk},
            )
            log_booking_event(
                booking,
                'Added to calendar',
                request.user,
                BookingLog.LOG_ADMIN,
                {'appointment_id': appointment.pk},
            )
            messages.success(request, 'Booking converted to an appointment.')
            return redirect('booking_requests')

        if action == 'cancel':
            booking.status = 'cancelled'
            booking.save()
            log_booking_event(
                booking,
                'Request cancelled',
                request.user,
                BookingLog.LOG_ADMIN,
                {'status': booking.status},
            )
            messages.success(request, 'Booking request cancelled.')
            return redirect('booking_requests')

    return render_booking_confirm()


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
