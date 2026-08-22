from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.contrib.auth.password_validation import validate_password

from core.images import validate_avatar

User = get_user_model()


class SignUpForm(UserCreationForm):
    full_name = forms.CharField(
        max_length=60,
        label="Full name",
        widget=forms.TextInput(attrs={"placeholder": "Full Name"}),
    )
    email = forms.EmailField(
        required=False,
        widget=forms.EmailInput(attrs={"placeholder": "Email"}),
    )

    class Meta:
        model = User
        fields = ("full_name", "username", "email", "password1", "password2")
        widgets = {
            "username": forms.TextInput(attrs={"placeholder": "Username"}),
        }

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data["email"]
        # The app's canonical "full name" field is display_name (used by the
        # Settings form and every identity payload). Storing it in first_name
        # meant the value entered at signup never appeared in Settings or in
        # any conversation header.
        user.display_name = self.cleaned_data["full_name"]
        if commit:
            user.save()
        return user


class LoginForm(AuthenticationForm):
    """Login form with a clear, user-facing invalid-credentials message."""

    error_messages = {
        "invalid_login": "Invalid username or password.",
        "inactive": "This account is inactive.",
    }


class UserProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ("display_name", "username", "email", "bio", "avatar")
        widgets = {
            "display_name": forms.TextInput(attrs={"placeholder": "Enter your full name"}),
            "username": forms.TextInput(attrs={"placeholder": "Enter your username"}),
            "email": forms.EmailInput(attrs={"placeholder": "Enter your email"}),
            "bio": forms.Textarea(attrs={"rows": 3, "placeholder": "Tell us about yourself..."}),
        }

    def __init__(self, *args, partial=False, **kwargs):
        super().__init__(*args, **kwargs)
        if partial:
            for field_name in list(self.fields.keys()):
                if field_name not in self.data:
                    del self.fields[field_name]

    def clean_username(self):
        username = self.cleaned_data["username"]
        if User.objects.filter(username__iexact=username).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("This username is already taken.")
        return username

    def clean_email(self):
        email = (self.cleaned_data.get("email") or "").strip().lower()
        if email and User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("This email is already in use.")
        return email

    def clean_avatar(self):
        avatar = self.cleaned_data.get("avatar")
        if not avatar:
            return avatar
        error = validate_avatar(avatar)
        if error:
            raise forms.ValidationError(error)
        return avatar


class PasswordChangeForm(forms.Form):
    current_password = forms.CharField(
        widget=forms.PasswordInput(attrs={"placeholder": "Enter current password"}),
    )
    new_password = forms.CharField(
        widget=forms.PasswordInput(attrs={"placeholder": "Enter new password"}),
    )
    confirm_password = forms.CharField(
        widget=forms.PasswordInput(attrs={"placeholder": "Confirm new password"}),
    )

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_current_password(self):
        current = self.cleaned_data.get("current_password")
        if current and not self.user.check_password(current):
            raise forms.ValidationError("Your current password is incorrect.")
        return current

    def clean_new_password(self):
        new = self.cleaned_data.get("new_password")
        if new:
            validate_password(new, user=self.user)
        return new

    def clean(self):
        cleaned = super().clean()
        new = cleaned.get("new_password")
        confirm = cleaned.get("confirm_password")
        if new and confirm and new != confirm:
            self.add_error("confirm_password", "Passwords do not match.")
        return cleaned

    def save(self):
        self.user.set_password(self.cleaned_data["new_password"])
        self.user.save(update_fields=["password"])
        return self.user
