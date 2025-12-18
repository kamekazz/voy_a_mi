from django import forms
from django.contrib.auth.forms import UserCreationForm
from .models import User, Order


class UserRegistrationForm(UserCreationForm):
    """Form for user registration."""
    email = forms.EmailField(required=True, widget=forms.EmailInput(attrs={
        'class': 'form-control',
        'placeholder': 'Email'
    }))

    class Meta:
        model = User
        fields = ['username', 'email', 'password1', 'password2']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['username'].widget.attrs.update({
            'class': 'form-control',
            'placeholder': 'Username'
        })
        self.fields['password1'].widget.attrs.update({
            'class': 'form-control',
            'placeholder': 'Password'
        })
        self.fields['password2'].widget.attrs.update({
            'class': 'form-control',
            'placeholder': 'Confirm Password'
        })


class OrderForm(forms.Form):
    """Form for placing a new order."""
    order_type = forms.ChoiceField(
        choices=Order.OrderType.choices,
        initial='market',
        widget=forms.RadioSelect(attrs={'class': 'btn-check'})
    )
    side = forms.ChoiceField(
        choices=Order.Side.choices,
        widget=forms.RadioSelect(attrs={'class': 'btn-check'})
    )
    contract_type = forms.ChoiceField(
        choices=Order.ContractType.choices,
        widget=forms.RadioSelect(attrs={'class': 'btn-check'})
    )
    price = forms.IntegerField(
        min_value=1,
        max_value=99,
        required=False,  # Not required for market orders
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': 'Price (1-99c)'
        })
    )
    quantity = forms.IntegerField(
        min_value=1,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': 'Quantity'
        })
    )

    def clean(self):
        cleaned_data = super().clean()
        order_type = cleaned_data.get('order_type')
        price = cleaned_data.get('price')

        # Price is required for limit orders
        if order_type == 'limit' and not price:
            raise forms.ValidationError("Price is required for limit orders.")

        # Validate price if provided
        if price is not None and (price < 1 or price > 99):
            raise forms.ValidationError("Price must be between 1 and 99 cents.")

        return cleaned_data

    def clean_quantity(self):
        quantity = self.cleaned_data.get('quantity')
        if quantity < 1:
            raise forms.ValidationError("Quantity must be at least 1.")
        return quantity


class QuickOrderForm(forms.Form):
    """Simplified form for quick buy/sell of YES/NO contracts."""
    order_type = forms.ChoiceField(
        choices=Order.OrderType.choices,
        initial='market',
        widget=forms.RadioSelect(attrs={'class': 'btn-check'})
    )
    price = forms.IntegerField(
        min_value=1,
        max_value=99,
        required=False,  # Not required for market orders
        widget=forms.NumberInput(attrs={
            'class': 'form-control form-control-lg',
            'placeholder': '50'
        })
    )
    quantity = forms.IntegerField(
        min_value=1,
        initial=10,
        widget=forms.NumberInput(attrs={
            'class': 'form-control form-control-lg',
            'placeholder': '10'
        })
    )

    def clean(self):
        cleaned_data = super().clean()
        order_type = cleaned_data.get('order_type')
        price = cleaned_data.get('price')

        # Price is required for limit orders
        if order_type == 'limit' and not price:
            raise forms.ValidationError("Price is required for limit orders.")

        return cleaned_data
