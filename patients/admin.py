from django.contrib import admin

from .models import Appointment, BookingConfig, BookingRequest, Patient, Payment


@admin.register(Patient)
class PatientAdmin(admin.ModelAdmin):
    list_display = (
        'patient_code',
        'first_name',
        'last_name',
        'phone',
        'payment_type',
        'language',
        'is_active',
    )
    readonly_fields = ('patient_code',)
    search_fields = ('id', 'first_name', 'last_name', 'phone', 'email')
    list_filter = ('language', 'payment_type', 'is_active')
    ordering = ('last_name', 'first_name')


@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    list_display = ('patient', 'date', 'time', 'visit_type', 'status')
    search_fields = ('patient__first_name', 'patient__last_name')
    list_filter = ('status', 'visit_type', 'date')
    ordering = ('date', 'time')


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('patient', 'amount', 'payment_method', 'date')
    search_fields = ('patient__first_name', 'patient__last_name')
    list_filter = ('payment_method', 'date')


@admin.register(BookingConfig)
class BookingConfigAdmin(admin.ModelAdmin):
    list_display = ('clinic_name', 'booking_enabled', 'accepting_new_patients')


@admin.register(BookingRequest)
class BookingRequestAdmin(admin.ModelAdmin):
    list_display = (
        'first_name',
        'last_name',
        'phone',
        'requested_date',
        'requested_time',
        'visit_type',
        'status',
        'created_at',
    )
    search_fields = ('first_name', 'last_name', 'phone', 'email')
    list_filter = ('status', 'visit_type', 'requested_date')
