import os
os.environ.setdefault("TYPEGUARD_DISABLE", "1")


import tkinter as tk
from pptx_linguistic_tool.app.main_window import App

def main():
    root = tk.Tk()
    App(root)
    root.mainloop()

if __name__ == "__main__":
    main()
