from django import forms

WIDGET_CLASSES = {
    forms.CheckboxInput: "checkbox",
    forms.CheckboxSelectMultiple: "checkbox-list",
    forms.RadioSelect: "radio-list",
    forms.Select: "select",
    forms.SelectMultiple: "select",
    forms.Textarea: "textarea",
    forms.ClearableFileInput: "file-input",
    forms.FileInput: "file-input",
}


def widget_css(widget) -> str:
    """The styleguide class for a widget."""
    if widget.attrs.get("type") == "color":
        return "input-colour"
    return next((css for kind, css in WIDGET_CLASSES.items() if type(widget) is kind), "input")


class StyledFormMixin:
    """Give each widget the class the styleguide uses for it."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            existing = widget.attrs.get("class", "")
            widget.attrs["class"] = f"{existing} {widget_css(widget)}".strip()
