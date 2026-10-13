from django import forms


class StyledFormMixin:
    """Give each widget the class the styleguide uses for it."""

    widget_classes = {
        forms.CheckboxInput: "checkbox",
        forms.CheckboxSelectMultiple: "checkbox-list",
        forms.RadioSelect: "radio-list",
        forms.Select: "select",
        forms.SelectMultiple: "select",
        forms.Textarea: "textarea",
        forms.ClearableFileInput: "file-input",
        forms.FileInput: "file-input",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            css = next(
                (value for kind, value in self.widget_classes.items() if type(widget) is kind),
                "input",
            )
            if widget.attrs.get("type") == "color":
                css = "input-colour"
            existing = widget.attrs.get("class", "")
            widget.attrs["class"] = f"{existing} {css}".strip()
