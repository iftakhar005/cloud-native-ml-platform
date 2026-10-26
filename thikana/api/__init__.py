"""The HTTP service around AddressParser.

Serving must stay light: nothing under thikana/api may import thikana/training
(which pulls in pandas). A test enforces it, because the Docker image will not
contain pandas.
"""
