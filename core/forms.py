from django import forms


class BootstrapFormMixin:
    """
    Adds Bootstrap's form-control / form-select / form-check-input classes
    to every field's widget automatically. Django's default widgets carry
    no CSS classes at all, so a template that just does `{{ field }}` in
    a loop (change_password.html, invite_employee.html, signup.html, etc.)
    renders plain unstyled <input> tags unless something adds these
    classes - this is that something, applied once here instead of
    repeated by hand on every form.

    Any form that wants Bootstrap-styled fields should inherit this
    FIRST, e.g. `class MyForm(BootstrapFormMixin, forms.Form):`.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            existing = widget.attrs.get("class", "")
            if isinstance(widget, (forms.CheckboxInput, forms.RadioSelect, forms.CheckboxSelectMultiple)):
                css_class = "form-check-input"
            elif isinstance(widget, (forms.Select, forms.SelectMultiple)):
                css_class = "form-select"
            else:
                css_class = "form-control"
            widget.attrs["class"] = f"{existing} {css_class}".strip()
