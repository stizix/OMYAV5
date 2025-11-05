from django import template
import markdown2

register = template.Library()

import markdown2
print("DEBUG:", markdown2)
@register.filter
def markdown(value):
    return markdown2.markdown(value) 