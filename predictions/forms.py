from django import forms
from .models import Order


class OrderForm(forms.Form):
    """Form for placing a new order."""
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

    def clean_price(self):
        price = self.cleaned_data.get('price')
        if price < 1 or price > 99:
            raise forms.ValidationError("Price must be between 1 and 99 cents.")
        return price

    def clean_quantity(self):
        quantity = self.cleaned_data.get('quantity')
        if quantity < 1:
            raise forms.ValidationError("Quantity must be at least 1.")
        return quantity


class QuickOrderForm(forms.Form):
    """Simplified form for quick buy/sell of YES/NO contracts."""
    price = forms.IntegerField(
        min_value=1,
        max_value=99,
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
