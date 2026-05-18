from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import PasswordChangeForm, SetPasswordForm, UserCreationForm

from .models import Appointment, BookingConfig, Patient, Payment


ROLE_ADMIN = 'Admin'
ROLE_ASSISTANT = 'Assistant'
ROLE_USER = 'User'
ROLE_CHOICES = [
    (ROLE_ASSISTANT, 'Assistant'),
    (ROLE_ADMIN, 'Admin'),
    (ROLE_USER, 'User'),
]


class CRMModelForm(forms.ModelForm):
    def _add_crm_classes(self):
        for field in self.fields.values():
            css_class = field.widget.attrs.get('class', '')
            field.widget.attrs['class'] = f'{css_class} crm-input'.strip()


class CRMFormMixin:
    def _add_crm_classes(self):
        for field in self.fields.values():
            widget = field.widget
            css_class = widget.attrs.get('class', '')
            widget.attrs['class'] = f'{css_class} crm-input'.strip()


class CRMPasswordChangeForm(CRMFormMixin, PasswordChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._add_crm_classes()


class CRMSetPasswordForm(CRMFormMixin, SetPasswordForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._add_crm_classes()


class UserPasswordTargetForm(CRMFormMixin, forms.Form):
    user = forms.ModelChoiceField(
        queryset=get_user_model().objects.none(),
        label='User',
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['user'].queryset = get_user_model().objects.order_by('username')
        self._add_crm_classes()


class CRMUserCreationForm(CRMFormMixin, UserCreationForm):
    role = forms.ChoiceField(choices=ROLE_CHOICES)
    first_name = forms.CharField(required=False)
    last_name = forms.CharField(required=False)
    email = forms.EmailField(required=False)

    class Meta:
        model = get_user_model()
        fields = ['username', 'first_name', 'last_name', 'email', 'role', 'password1', 'password2']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._add_crm_classes()


class CRMUserUpdateForm(CRMFormMixin, forms.ModelForm):
    role = forms.ChoiceField(choices=ROLE_CHOICES)

    class Meta:
        model = get_user_model()
        fields = ['username', 'first_name', 'last_name', 'email', 'role', 'is_active']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            if self.instance.is_superuser or self.instance.groups.filter(name=ROLE_ADMIN).exists():
                self.fields['role'].initial = ROLE_ADMIN
            elif self.instance.groups.filter(name=ROLE_ASSISTANT).exists():
                self.fields['role'].initial = ROLE_ASSISTANT
            else:
                self.fields['role'].initial = ROLE_USER
        self._add_crm_classes()


class PatientForm(CRMModelForm):
    patient_code = forms.CharField(
        label='Patient ID',
        required=False,
        disabled=True,
    )

    class Meta:
        model = Patient
        fields = [
            'patient_code',
            'first_name',
            'last_name',
            'date_of_birth',
            'phone',
            'email',
            'language',
            'payment_type',
            'insurance_notes',
            'is_active',
        ]
        widgets = {
            'date_of_birth': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
            'insurance_notes': forms.Textarea(attrs={'rows': 4}),
        }
        labels = {
            'insurance_notes': 'Patient profile notes',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields['patient_code'].initial = self.instance.patient_code
        else:
            self.fields['patient_code'].initial = 'Assigned automatically'
        self._add_crm_classes()
        self.fields['date_of_birth'].input_formats = ['%Y-%m-%d']


class PatientAppointmentChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, patient):
        return f'{patient.patient_code} - {patient.first_name} {patient.last_name} - {patient.phone}'


class AppointmentForm(CRMModelForm):
    patient = PatientAppointmentChoiceField(queryset=Patient.objects.none())

    class Meta:
        model = Appointment
        fields = ['patient', 'date', 'time', 'visit_type', 'status', 'notes']
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
            'time': forms.TimeInput(attrs={'type': 'time'}),
            'notes': forms.Textarea(attrs={'rows': 4}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._add_crm_classes()
        self.fields['patient'].queryset = Patient.objects.order_by('last_name', 'first_name')


class PaymentForm(CRMModelForm):
    class Meta:
        model = Payment
        fields = ['patient', 'appointment', 'amount', 'payment_method', 'notes']
        widgets = {
            'amount': forms.NumberInput(attrs={'step': '0.01', 'min': '0'}),
            'notes': forms.Textarea(attrs={'rows': 4}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._add_crm_classes()
        self.fields['patient'].queryset = Patient.objects.order_by('last_name', 'first_name')
        self.fields['appointment'].queryset = Appointment.objects.select_related('patient').order_by(
            '-date',
            '-time',
        )


class BookingConfigForm(forms.ModelForm):
    class Meta:
        model = BookingConfig
        fields = '__all__'
        widgets = {
            'welcome_message': forms.Textarea(attrs={'rows': 3, 'class': 'crm-textarea'}),
            'welcome_message_es': forms.Textarea(attrs={'rows': 3, 'class': 'crm-textarea'}),
            'offline_message': forms.Textarea(attrs={'rows': 2, 'class': 'crm-textarea'}),
            'available_slots_monday': forms.TextInput(
                attrs={'class': 'crm-input', 'placeholder': '9:30,10:00,10:30,11:00'}
            ),
            'available_slots_tuesday': forms.TextInput(attrs={'class': 'crm-input'}),
            'available_slots_wednesday': forms.TextInput(
                attrs={'class': 'crm-input', 'placeholder': '9:30,10:00,10:30,11:00'}
            ),
            'available_slots_thursday': forms.TextInput(
                attrs={'class': 'crm-input', 'placeholder': '9:30,10:00,10:30,11:00'}
            ),
            'available_slots_friday': forms.TextInput(attrs={'class': 'crm-input'}),
            'available_slots_saturday': forms.TextInput(attrs={'class': 'crm-input'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            css_class = widget.attrs.get('class', '')
            if isinstance(widget, forms.Select):
                css_class = f'{css_class} crm-select'.strip()
            elif not isinstance(widget, forms.CheckboxInput):
                css_class = f'{css_class} crm-input'.strip()
            widget.attrs['class'] = css_class
