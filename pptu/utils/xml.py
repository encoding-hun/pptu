from bs4 import BeautifulSoup


def load_html(html):
    return BeautifulSoup(html, "lxml-html")
