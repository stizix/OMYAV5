from django import forms

class CourseUploadForm(forms.Form):
    title = forms.CharField(max_length=200)
    description = forms.CharField(widget=forms.Textarea, required=False)
    audio_file = forms.FileField(required=False)
    text_input = forms.CharField(widget=forms.Textarea, required=False)
    text_file = forms.FileField(required=False)
    language = forms.ChoiceField(
        choices=[
            ("fr", "Français"),
            ("en", "English"),
            ("es", "Español"),
            ("de", "Deutsch"),
            ("it", "Italiano"),
        ],
        initial="fr",
        required=True,
        label="Langue",
    )

    def clean(self):
        cleaned = super().clean()
        audio = cleaned.get("audio_file")
        text_input = cleaned.get("text_input")
        text_file = cleaned.get("text_file")

        sources = [bool(audio), bool(text_input and text_input.strip()), bool(text_file)]
        if sum(sources) == 0:
            raise forms.ValidationError("Fournis soit un audio, soit un texte (champ ou fichier).")
        if sum(sources) > 1:
            raise forms.ValidationError("Une seule source à la fois : audio OU texte.")
        return cleaned

