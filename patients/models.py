from django.db import models


class Patient(models.Model):
    LANGUAGE_SPANISH = 'es'
    LANGUAGE_ENGLISH = 'en'
    LANGUAGE_CHOICES = [
        (LANGUAGE_SPANISH, 'Español'),
        (LANGUAGE_ENGLISH, 'English'),
    ]

    PAYMENT_CASH = 'cash'
    PAYMENT_MEMBERSHIP = 'membership'
    PAYMENT_TYPE_CHOICES = [
        (PAYMENT_CASH, 'Cash'),
        (PAYMENT_MEMBERSHIP, 'Membership'),
    ]

    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    date_of_birth = models.DateField(null=True, blank=True)
    phone = models.CharField(max_length=20)
    email = models.EmailField(null=True, blank=True)
    language = models.CharField(
        max_length=20,
        choices=LANGUAGE_CHOICES,
        default=LANGUAGE_SPANISH,
    )
    payment_type = models.CharField(
        max_length=20,
        choices=PAYMENT_TYPE_CHOICES,
        default=PAYMENT_CASH,
    )
    insurance_notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def patient_code(self):
        code_number = max(self.id - 1, 0) if self.id else 0
        return str(code_number).zfill(5)

    def __str__(self):
        return f'{self.patient_code} - {self.first_name} {self.last_name}'


class Appointment(models.Model):
    VISIT_TYPE_NEW = 'new'
    VISIT_TYPE_FOLLOWUP = 'followup'
    VISIT_TYPE_ANNUAL = 'annual'
    VISIT_TYPE_URGENT = 'urgent'
    VISIT_TYPE_TELEMEDICINE = 'telemedicine'
    VISIT_TYPE_CHOICES = [
        (VISIT_TYPE_NEW, 'New Patient'),
        (VISIT_TYPE_FOLLOWUP, 'Follow Up'),
        (VISIT_TYPE_ANNUAL, 'Annual Exam'),
        (VISIT_TYPE_URGENT, 'Urgent Visit'),
        (VISIT_TYPE_TELEMEDICINE, 'Telemedicine'),
    ]

    STATUS_PENDING = 'pending'
    STATUS_CONFIRMED = 'confirmed'
    STATUS_COMPLETED = 'completed'
    STATUS_CANCELLED = 'cancelled'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_CONFIRMED, 'Confirmed'),
        (STATUS_COMPLETED, 'Completed'),
        (STATUS_CANCELLED, 'Cancelled'),
    ]

    patient = models.ForeignKey(Patient, on_delete=models.CASCADE)
    date = models.DateField()
    time = models.TimeField()
    visit_type = models.CharField(
        max_length=20,
        choices=VISIT_TYPE_CHOICES,
        default=VISIT_TYPE_NEW,
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.patient} - {self.date} {self.time}'


class Payment(models.Model):
    PAYMENT_METHOD_CASH = 'cash'
    PAYMENT_METHOD_CARD = 'card'
    PAYMENT_METHOD_ZELLE = 'zelle'
    PAYMENT_METHOD_CHOICES = [
        (PAYMENT_METHOD_CASH, 'Cash'),
        (PAYMENT_METHOD_CARD, 'Card'),
        (PAYMENT_METHOD_ZELLE, 'Zelle'),
    ]

    patient = models.ForeignKey(Patient, on_delete=models.CASCADE)
    appointment = models.ForeignKey(
        Appointment,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    amount = models.DecimalField(max_digits=8, decimal_places=2)
    payment_method = models.CharField(
        max_length=20,
        choices=PAYMENT_METHOD_CHOICES,
        default=PAYMENT_METHOD_CASH,
    )
    date = models.DateField(auto_now_add=True)
    notes = models.TextField(blank=True)

    def __str__(self):
        return f'{self.patient} - {self.amount}'


class BookingConfig(models.Model):
    clinic_name = models.CharField(max_length=200, default='Oak & Vine Health Center')
    welcome_message = models.TextField(
        default='Book your appointment online. We will confirm within 24 hours.'
    )
    welcome_message_es = models.TextField(
        default='Reserve su cita en linea. Confirmaremos en menos de 24 horas.'
    )

    show_new_patient = models.BooleanField(default=True)
    show_followup = models.BooleanField(default=True)
    show_annual_exam = models.BooleanField(default=True)
    show_urgent = models.BooleanField(default=True)
    show_telemedicine = models.BooleanField(default=True)

    available_slots_monday = models.CharField(
        max_length=500,
        blank=True,
        default='9:30,10:00,10:30,11:00,11:30,12:00,12:30,13:00,13:30,14:00',
    )
    available_slots_tuesday = models.CharField(
        max_length=500,
        blank=True,
        default='',
        help_text='Leave empty = by appointment only',
    )
    available_slots_wednesday = models.CharField(
        max_length=500,
        blank=True,
        default='9:30,10:00,10:30,11:00,11:30,12:00,12:30,13:00,13:30,14:00',
    )
    available_slots_thursday = models.CharField(
        max_length=500,
        blank=True,
        default='9:30,10:00,10:30,11:00,11:30,12:00,12:30,13:00,13:30,14:00',
    )
    available_slots_friday = models.CharField(
        max_length=500,
        blank=True,
        default='',
        help_text='Leave empty = by appointment only',
    )
    available_slots_saturday = models.CharField(
        max_length=500,
        blank=True,
        default='',
        help_text='Leave empty = by appointment only',
    )

    min_days_ahead = models.IntegerField(
        default=1,
        help_text='Minimum days in advance to book',
    )
    max_days_ahead = models.IntegerField(
        default=30,
        help_text='Maximum days ahead patients can book',
    )
    accepting_new_patients = models.BooleanField(default=True)
    require_phone = models.BooleanField(default=True)
    require_email = models.BooleanField(default=False)

    notify_email = models.EmailField(
        blank=True,
        default='admin@oakvine.com',
        help_text='Email to notify when new booking arrives',
    )

    booking_enabled = models.BooleanField(
        default=True,
        help_text='Turn off to disable online booking completely',
    )
    offline_message = models.TextField(
        blank=True,
        default='Online booking is temporarily unavailable. Please call us.',
    )

    class Meta:
        verbose_name = 'Booking Configuration'

    def __str__(self):
        return f'Booking Config - {self.clinic_name}'


class BookingRequest(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending Review'),
        ('confirmed', 'Confirmed'),
        ('cancelled', 'Cancelled'),
        ('converted', 'Converted to Appointment'),
    ]

    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    phone = models.CharField(max_length=20)
    email = models.EmailField(blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    language = models.CharField(
        max_length=2,
        choices=[('es', 'Spanish'), ('en', 'English')],
        default='es',
    )
    is_new_patient = models.BooleanField(default=True)

    requested_date = models.DateField()
    requested_time = models.CharField(max_length=10)
    visit_type = models.CharField(max_length=50)
    notes = models.TextField(blank=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    converted_to_appointment = models.ForeignKey(
        'Appointment',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='booking_request',
    )

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.first_name} {self.last_name} - {self.requested_date}'
