from django import forms

from .models import Profile

MAX_AVATAR_MB = 5


class ProfileForm(forms.ModelForm):
    class Meta:
        model = Profile
        fields = ['avatar', 'display_name', 'bio']
        widgets = {
            'display_name': forms.TextInput(attrs={'placeholder': 'Your name'}),
            'bio': forms.Textarea(attrs={'rows': 4, 'maxlength': 300, 'placeholder': 'Say something about yourself'}),
        }
        labels = {'avatar': 'Profile photo', 'display_name': 'Name'}

    def clean_avatar(self):
        avatar = self.cleaned_data.get('avatar')
        if avatar and hasattr(avatar, 'size') and avatar.size > MAX_AVATAR_MB * 1024 * 1024:
            raise forms.ValidationError(f'Please choose a photo under {MAX_AVATAR_MB} MB.')
        return avatar
