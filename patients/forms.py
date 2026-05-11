from django import forms

from .models import Appointment, BookingConfig, Patient, Payment


class CRMModelForm(forms.ModelForm):
    def _add_crm_classes(self):
        for field in self.fields.values():
            css_class = field.widget.attrs.get('class', '')
            field.widget.attrs['class'] = f'{css_class} crm-input'.strip()


class PatientForm(CRMModelForm):
    class Meta:
        model = Patient
        fields = [
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
            'date_of_birth': forms.DateInput(attrs={'type': 'date'}),
            'insurance_notes': forms.Textarea(attrs={'rows': 4}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._add_crm_classes()


class AppointmentForm(CRMModelForm):
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
