from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor


OUT = Path('/home/ums-08/emg2026/dokumenti/Upute_EMG_2026-10-30.docx')
doc = Document()
section = doc.sections[0]
section.page_width, section.page_height = Cm(21), Cm(29.7)
section.top_margin = section.bottom_margin = Cm(1.65)
section.left_margin = section.right_margin = Cm(1.8)

styles = doc.styles
for name in ['Normal', 'Title', 'Subtitle', 'Heading 1', 'Heading 2', 'List Bullet', 'List Number']:
    style = styles[name]
    style.font.name = 'Liberation Sans'
    style.font.color.rgb = RGBColor(0, 0, 0)
    style.paragraph_format.space_after = Pt(4)
styles['Normal'].font.size = Pt(10)
styles['Normal'].paragraph_format.line_spacing = 1.04
styles['Title'].font.size = Pt(19)
styles['Title'].paragraph_format.space_after = Pt(3)
styles['Subtitle'].font.size = Pt(9)
for name in ['Heading 1', 'Heading 2']:
    styles[name].font.size = Pt(11.5)
    styles[name].font.bold = True
    styles[name].paragraph_format.space_before = Pt(7)
    styles[name].paragraph_format.space_after = Pt(3)
for name in ['List Bullet', 'List Number']:
    styles[name].font.size = Pt(10)
    styles[name].paragraph_format.space_after = Pt(4)


def p(text, style=None):
    return doc.add_paragraph(text, style)


def h(text):
    doc.add_heading(text, level=1)


def code(text):
    paragraph = doc.add_paragraph()
    paragraph.paragraph_format.space_before = Pt(1)
    paragraph.paragraph_format.space_after = Pt(5)
    paragraph.paragraph_format.line_spacing = 1.0
    paragraph.paragraph_format.keep_together = True
    run = paragraph.add_run(text)
    run.font.name = 'Liberation Mono'
    run.font.size = Pt(8.5)


def item(label, text):
    paragraph = doc.add_paragraph(style='List Bullet')
    paragraph.add_run(label + ' ').bold = True
    paragraph.add_run(text)


p('Pokretanje EMG laboratorijskog sustava', 'Title')
p('Tri Shimmera i Vernier dinamometar   |   Bilješke s vježbe 30. 10. 2026.', 'Subtitle')
p('Upute vrijede za računalo ums08-l6 i projekt /home/ums-08/emg2026. '
  'Pokrećemo šest sirovih EMG kanala i silu stiska u N. Četvrti Shimmer 9D23 '
  'izostavljen je jer nije ostvareno valjano očitanje.')

table = doc.add_table(rows=1, cols=4)
table.alignment = WD_TABLE_ALIGNMENT.CENTER
table.autofit = False
widths = [2.8, 5.3, 3.9, 5.4]
rows = [
    ['Uređaj', 'Bluetooth adresa', 'Port', 'Kanal i ROS namespace'],
    ['Shimmer 1  4C91', '00:06:66:B1:4C:91', '/dev/rfcomm0', '1   /shimmer1'],
    ['Shimmer 2  9D2C', '60:8A:10:40:9D:2C', '/dev/rfcomm1', '6   /shimmer2'],
    ['Shimmer 3  4C87', '00:06:66:B1:4C:87', '/dev/rfcomm2', '1   /shimmer3'],
]
for index, values in enumerate(rows):
    cells = table.rows[0].cells if index == 0 else table.add_row().cells
    for col, (cell, value) in enumerate(zip(cells, values)):
        cell.width = Cm(widths[col])
        cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        cell.text = value
        props = cell._tc.get_or_add_tcPr()
        borders = OxmlElement('w:tcBorders')
        for side in ['top', 'left', 'bottom', 'right']:
            border = OxmlElement('w:' + side)
            border.set(qn('w:val'), 'single')
            border.set(qn('w:sz'), '4')
            border.set(qn('w:color'), 'D9D9D9')
            borders.append(border)
        props.append(borders)
        margins = OxmlElement('w:tcMar')
        for side in ['top', 'left', 'bottom', 'right']:
            margin = OxmlElement('w:' + side)
            margin.set(qn('w:w'), '70')
            margin.set(qn('w:type'), 'dxa')
            margins.append(margin)
        props.append(margins)
        if index == 0:
            shade = OxmlElement('w:shd')
            shade.set(qn('w:fill'), 'E7EDF3')
            props.append(shade)
        for paragraph in cell.paragraphs:
            paragraph.paragraph_format.space_after = Pt(0)
            for run in paragraph.runs:
                run.font.size = Pt(8.5)
                run.bold = index == 0
header = OxmlElement('w:tblHeader')
table.rows[0]._tr.get_or_add_trPr().append(header)

h('1 Priprema uređaja i portova')
p('Uključiti Bluetooth, sva tri Shimmera i dinamometar. Za probu ostaviti Shimmere '
  'izvan docka. Ako portovi nisu već vezani, izvršiti sljedeće naredbe. '
  'Uparivanje je opisano na drugoj stranici.')
code('sudo rfcomm bind 0 00:06:66:B1:4C:91 1\n'
     'sudo rfcomm bind 1 60:8A:10:40:9D:2C 6\n'
     'sudo rfcomm bind 2 00:06:66:B1:4C:87 1')

h('2 Priprema svakog novog terminala')
code('source /opt/ros/humble/setup.bash\n'
     'cd /home/ums-08/emg2026\n'
     'source install/setup.bash')
p('Ako se mijenjao kod: prvo colcon build --symlink-install, zatim ponovno '
  'source install/setup.bash. Ne pokretati dva publishera na istom portu.')

h('3 Terminal 1 pokretanje triju Shimmera')
code('ros2 launch shimmer_ros2 publish_three_emg.launch.py')
p('Čvorovi se pokreću u razmacima od 20 s. Pričekati približno jednu minutu '
  'i poruku Publishing EMG data za sva tri uređaja. Zadano je oko 993 Hz, '
  'gain 12 i interno nuliranje ADC-a prije mjerenja.')

h('4 Terminal 2 pokretanje dinamometra')
code('ros2 launch godirect_ros2 publish_grip_force.launch.py')
p('Očekivani naziv je GDX-HD 151025S9. Tijekom početnog nuliranja od 4 s '
  'držati ručku neopterećenom. Zadana frekvencija je 200 Hz.')

h('5 Terminal 3 prikaz grafova')
code('layout_file="$PWD/src/godirect_ros2/config/plotjuggler_three_shimmers_config.xml"\n'
     'ros2 run plotjuggler plotjuggler --layout "$layout_file" --start_streamer')
p('U dijalogu potvrditi /shimmer1/emg_stream, /shimmer2/emg_stream, '
  '/shimmer3/emg_stream i /grip_force_stream. Ako prijenos nije aktivan, '
  'kliknuti Start. Dok radi, gumb prikazuje Stop. Plavo i narančasto su dva EMG kanala.')

doc.add_page_break()
h('Što smo napravili danas')
item('Povezali uređaje.', 'Uparili smo senzore, razdvojili ih u tri ROS namespacea '
     'i povezali dinamometar. Drugi Shimmer koristi RFCOMM kanal 6; prvi i treći kanal 1.')
item('Popravili čitanje paketa.', 'Pogrešno poravnanje bajtova stvaralo je lažne pilaste '
     'grafove i pogreške prijenosa. Dodana je provjera triju zaglavlja i dvaju intervala '
     'Shimmerova brojača prije prihvaćanja uzorka.')
item('Popravili ponovno pokretanje.', 'Zaustavljanje sada čeka smirivanje prijenosa '
     'umjesto da proizvoljan bajt 0xFF u podacima prihvati kao dovršetak. Dodani su '
     'timeout pri čekanju ACK-a i provjera odgovora s nazivom uređaja. Četiri testa prolaze.')
item('Pripremili grafove i zajednički launch.', 'Datoteke publish_three_emg.launch.py '
     'i plotjuggler_three_shimmers_config.xml pokrivaju tri senzora i prikaz sile. '
     'Testirali smo prijenos, dodir kontakata i stiske dinamometra; stvarni mišićni EMG '
     'još nije provjeren jer elektrode nisu bile spojene.')
p('Za neispravan 9D23 spremljena je izvorna konfiguracija u '
  'diagnostics/9D23/sdlog.original.cfg. Probno je na njegovoj SD kartici promijenjen '
  'baud_rate s 11 na 9, ali rad nije potvrđen. Taj uređaj zasad ne koristimo.')

h('Brza provjera i oporavak')
code('ros2 topic list\n'
     'python3 /home/ums-08/emg2026/check_shimmers.py\n'
     'ros2 topic echo /grip_force_stream --once')
p('Skripta promatra 10 s i ispisuje primljene uzorke i frekvenciju iz ROS oznaka. '
  'Nula za shimmer4 je očekivana. Broj poruka sam po sebi ne potvrđuje kvalitetu '
  'EMG-a ni preciznost sinkronizacije. U nekim provjerama primljeno je oko '
  '993 uzorka/s po uređaju; uz Bluetooth skeniranje i zajednički promet bilo je padova.')
p('Ako nema podataka, pogledati ispis pripadnog čvora i rfcomm -a. Za ponovno '
  'pokretanje prvo Ctrl+C u njegovu terminalu, pa pričekati zatvaranje veze. '
  'Pogrešno vezan port osloboditi naredbom sudo rfcomm release N i ponovno ga '
  'vezati prema tablici. Ako je dinamometar ugašen, uključiti ga tipkom.')
p('Na kraju rada zaustaviti senzorske čvorove s Ctrl+C u njihovim terminalima '
  'i zatvoriti PlotJuggler.')
p('Pri prvom uparivanju otvoriti bluetoothctl i izvršiti agent on, default-agent '
  'i scan on. Za svaku adresu iz tablice izvršiti pair MAC pa trust MAC; '
  'standardni PIN je 1234. Završiti sa scan off i quit. Ako port javlja Permission '
  'denied, dodati korisnika u dialout: sudo usermod -aG dialout "$USER", '
  'zatim se odjaviti i ponovno prijaviti.')

h('Što radimo sljedeće')
for text in [
    'S nastavnikom pravilno postaviti elektrode jednog Shimmera i referentnu '
    'elektrodu. Snimiti opuštenu ruku, nekoliko kontrakcija uz dinamometar i ponovno '
    'opuštanje. Dodir kontakata bez elektroda služi samo provjeri ulaza.',
    'Provjeriti izvornu vremensku bazu, kašnjenje, izgubljene uzorke i ostvarene '
    'frekvencije. Zatim uključiti postojeću obradu EMG-a i prikazati sirovi EMG, '
    'obrađeni EMG i silu na usporedivoj vremenskoj osi.',
    'Implementirati servis za kalibracijski eksperiment od 30 s i pohranu oba '
    'signala s vremenskim oznakama. Prije eksperimenta odrediti MVC, referentnu '
    'maksimalnu voljnu silu. Plan: 100, 75, 50 i 25 % MVC po 6 s, '
    'nakon svake razine 1,5 s mirovanja; ukupna razina 0 % također traje 6 s.',
    'Dodati servis za treniranje jednostavne regresije i čvor za procjenu sile '
    'uživo. Provjeriti točnost na zasebnom pokušaju koji nije korišten za treniranje.',
    'Nakon provjere sustava prikupiti dokumentirane podatke 5–10 osoba uz '
    'pristanak i snimiti demonstraciju. Koopman predikciju razmotriti s nastavnicima '
    'nakon osnovnog regresijskog modela.',
]:
    p(text, 'List Number')

doc.core_properties.title = 'Pokretanje EMG laboratorijskog sustava'
doc.core_properties.subject = 'Upute za pokretanje i bilješke s vježbe 30. 10. 2026.'
doc.core_properties.author = ''
for border in list(doc.styles.element.xpath('//w:pBdr')):
    border.getparent().remove(border)
for border in list(doc.element.xpath('//w:pBdr')):
    border.getparent().remove(border)
OUT.parent.mkdir(parents=True, exist_ok=True)
doc.save(OUT)
print(OUT)
