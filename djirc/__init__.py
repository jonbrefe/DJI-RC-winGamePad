"""djirc: reusable library for the DJI RC-N1/N3 over its VCOM "For Protocol" port.

Submodules:
  protocol  DUML framing, checksums, decoding, and the high-level Controller.
  reader    Reader background thread that polls the controller and reconnects.
  gui       Skeuomorphic Tk controller view (run_gui); imports tkinter on use.

`gui` is intentionally not imported here so importing the library does not pull in
tkinter; import it explicitly (e.g. ``from djirc import gui``) when needed.
"""
from . import protocol
from .protocol import Controller

__all__ = ["protocol", "Controller"]
