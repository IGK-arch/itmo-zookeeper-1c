"""Build the report using the measured experiments and unchanged browser screenshots."""
import hashlib
import html
import json
from pathlib import Path

import bootstrap
from bootstrap import ROOT
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (Flowable, KeepTogether, PageBreak, Paragraph,
                               Preformatted, SimpleDocTemplate, Spacer, Table, TableStyle)

OUT = ROOT / 'output/pdf/Карташов_Игорь_J3312_ZooKeeper.pdf'
REPO = 'https://github.com/IGK-arch/itmo-zookeeper-1c'
W = A4[0] - 36 * mm
for font, file in [('Times', 'times.ttf'), ('Times-Bold', 'timesbd.ttf'),
                   ('Times-Italic', 'timesi.ttf'), ('Mono', 'consola.ttf')]:
    pdfmetrics.registerFont(TTFont(font, 'C:/Windows/Fonts/' + file))
pdfmetrics.registerFontFamily('Times', normal='Times', bold='Times-Bold', italic='Times-Italic')
styles = {
    'body': ParagraphStyle('body', fontName='Times', fontSize=11.5, leading=14.7,
                           alignment=TA_JUSTIFY, spaceAfter=8),
    'h1': ParagraphStyle('h1', fontName='Times-Bold', fontSize=15.5, leading=19.5, spaceAfter=11),
    'h2': ParagraphStyle('h2', fontName='Times-Bold', fontSize=12.4, leading=15.5, spaceBefore=8, spaceAfter=8),
    'cell': ParagraphStyle('cell', fontName='Times', fontSize=10.4, leading=12.7),
    'head': ParagraphStyle('head', fontName='Times-Bold', fontSize=10.3, leading=12.7),
    'caption': ParagraphStyle('caption', fontName='Times-Italic', fontSize=10, leading=12.2,
                              alignment=TA_CENTER, spaceBefore=5, spaceAfter=9),
    'code': ParagraphStyle('code', fontName='Mono', fontSize=8.6, leading=11,
                           spaceBefore=3, spaceAfter=9, backColor=colors.HexColor('#f1f2f4'), borderPadding=5),
}
story, views = [], []


def read(path):
    return json.loads((ROOT / path).read_text(encoding='utf-8'))


def p(text, style='body'):
    story.append(Paragraph(text, styles[style]))


def h(text):
    p(text, 'h1')


def sub(text):
    p(text, 'h2')


def code(text):
    story.append(Preformatted(text, styles['code']))


def table(headers, rows, widths):
    def cell(value, style):
        return Paragraph(html.escape(str(value)).replace('\n', '<br/>'), styles[style])
    data = [[cell(v, 'head') for v in headers]] + [[cell(v, 'cell') for v in row] for row in rows]
    result = Table(data, colWidths=widths, repeatRows=1)
    result.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e9edf1')),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LINEBELOW', (0, 0), (-1, 0), 0.65, colors.HexColor('#9ba7b2')),
        ('LINEBELOW', (0, 1), (-1, -1), 0.3, colors.HexColor('#d0d7df')),
        ('LEFTPADDING', (0, 0), (-1, -1), 6), ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 5), ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
    ]))
    story.extend([result, Spacer(1, 8)])


class Screen(Flowable):
    def __init__(self, meta):
        super().__init__()
        self.path = ROOT / 'evidence/screenshots' / meta['file']
        self.reader = ImageReader(str(self.path))
        self.code_font_pt = W / meta['width'] * 18
        iw, ih = self.reader.getSize()
        # Verified against the original JPEGs: page content is captured at 1 px per CSS px.
        # The capture canvas has extra space at the right/bottom; it must not set the scale.
        self.box = [meta['x'] - 2, meta['y'] - 2, meta['width'] + 4, meta['height'] + 4]
        self.width = W
        self.height = W * self.box[3] / self.box[2]
        self.hAlign = 'CENTER'

    def draw(self):
        iw, ih = self.reader.getSize()
        x, y, w, height = self.box
        assert 0 <= x and 0 <= y and x+w <= iw and y+height <= ih
        scale = self.width / w
        c = self.canv
        c.saveState()
        clip = c.beginPath()
        clip.rect(0, 0, self.width, self.height)
        c.clipPath(clip, stroke=0)
        c.drawImage(self.reader, -x*scale, self.height-(ih-y)*scale, iw*scale, ih*scale)
        c.restoreState()
        px, py = c.absolutePosition(0, 0)
        views.append({'source': self.path.name, 'sha256': hashlib.sha256(self.path.read_bytes()).hexdigest(),
                      'source_size': [iw, ih], 'source_box': self.box, 'page': c.getPageNumber(),
                      'page_box': [px, py, px+self.width, py+self.height], 'effective_code_font_pt': self.code_font_pt})


captures = {row['page']: row for row in read('evidence/screenshots/captures.json')}


def screen(key, caption):
    story.append(KeepTogether([Screen(captures[key]), Paragraph(caption, styles['caption'])]))


def page():
    story.append(PageBreak())


unsafe, safe = read('evidence/experiments.json')[-2:]
ephemeral = read('evidence/ephemeral.json')
verification = read('evidence/full-verification.json')
assert verification['passed'] and len(verification['checks']) == 4
assert unsafe['accepted_publications'] == 2 and unsafe['pointer_version'] == 2
assert safe['accepted_publications'] == 1 and safe['pointer']['coordinator'] == 'B'

def dec(value):
    return f'{value:.3f}'.replace('.', ',')


# 1. Title.
p('МИНИСТЕРСТВО НАУКИ И ВЫСШЕГО ОБРАЗОВАНИЯ<br/>РОССИЙСКОЙ ФЕДЕРАЦИИ', 'caption')
story.append(Spacer(1, 7*mm))
p('УНИВЕРСИТЕТ ИТМО', 'caption')
story.append(Spacer(1, 35*mm))
p('ОТЧЁТ ПО ЛАБОРАТОРНОЙ РАБОТЕ 4', 'caption')
story.append(Paragraph('Apache ZooKeeper', ParagraphStyle('title', fontName='Times-Bold', fontSize=23, leading=29, alignment=TA_CENTER, spaceAfter=15)))
story.append(Paragraph('Обеспечение отказоустойчивости<br/>и защита от устаревших записей', ParagraphStyle('subtitle', fontName='Times', fontSize=16, leading=22, alignment=TA_CENTER)))
story.append(Spacer(1, 11*mm))
p('Вариант 1: программист, разработчик на 1С', 'caption')
story.append(Spacer(1, 25*mm))
story.append(Paragraph('Выполнил:<br/>Карташов Игорь Олегович<br/>Группа J3312', ParagraphStyle('author', fontName='Times', fontSize=14, leading=20, alignment=TA_RIGHT)))
story.append(Spacer(1, 35*mm))
p('Санкт-Петербург<br/>2026', 'caption')
page()

# 2. Setup and roles.
h('1. Развёртывание ансамбля')
p('Развернул три копии Apache ZooKeeper 3.9.6 на Windows с Java 17 '
  '(Temurin 17.0.20.1+1). В JAVA_HOME указал папку runtime/jdk-17.0.20.1+1. '
  'Каждую копию запускал штатной командой bin\\zkServer.cmd из её каталога servers/zkN.')
table(['Сервер / myid', 'Клиент', 'Кворум', 'Выборы', 'dataDir'],
      [['zk1 / 1', 2181, 2888, 3888, '../zk1/data'],
       ['zk2 / 2', 2182, 2889, 3889, '../zk2/data'],
       ['zk3 / 3', 2183, 2890, 3890, '../zk3/data']], [90, 65, 65, 65, W-285])
p('В conf/zoo.cfg у всех трёх серверов одинаковый список участников. '
  'Каталоги данных отдельные, в каждом лежит свой файл myid с числом 1, 2 или 3. '
  'Для сессий задан тайм-аут 10 секунд; tickTime равен 2000 мс.')
code('server.1=127.0.0.1:2888:3888\nserver.2=127.0.0.1:2889:3889\nserver.3=127.0.0.1:2890:3890')
p('Проверил роли командой srvr: zk3 стал лидером, zk1 и zk2 - последователями. '
  'Все три процесса работают на одном ПК; в опытах проверял отказ отдельных процессов.')
screen('roles', 'Рисунок 1. Ответы srvr трёх серверов в локальной консоли')
page()

# 3. Quorum.
h('2. Потеря одного и двух серверов')
p('Сначала остановил zk1. Оставшиеся zk2 и zk3 сохранили кворум: '
  'новое значение записалось и прочиталось обратно. Затем остановил zk2. '
  'Процесс zk3 продолжал работать, но перестал обслуживать запросы ZooKeeper.')
screen('quorum', 'Рисунок 2. Проверка записи и чтения при 3, 2 и 1 работающем сервере')
p('При одном оставшемся сервере srvr вернул «This ZooKeeper instance is not currently serving requests», '
  'а попытка подключения клиента завершилась KazooTimeoutError. '
  'После запуска zk1 и zk2 снова появились один лидер и два последователя, запись и чтение восстановились.')
p('Для трёх участников кворум равен двум. Поэтому потеря одного сервера допустима, '
  'а потеря двух останавливает обслуживание запросов.')
page()

# 4. Ephemeral node and calculation.
h('3. Эфемерный узел')
p('В zkCli создал узел командой create -e и проверил его через get -s из другого клиента. '
  f'Поле ephemeralOwner было ненулевым: {ephemeral["ephemeral_owner"]}. '
  'После команды quit в клиенте-владельце повторный запуск get -s вернул Node does not exist.')
screen('ephemeral', 'Рисунок 3. Узел существует до закрытия сессии и исчезает после него')
sub('4. Координатор расчёта пар навыков')
p('Использовал тот же CSV из s3://hh-lake/raw/it_vacancies_2024.csv и вариант 1С из работы 3. '
  'Отбирал роль «Программист, разработчик» и названия с 1С/1C и словами '
  '«программист», «разработчик», developer или programmer. '
  'Битрикс/Bitrix и Java Developer исключил. Навыки приводил к нижнему регистру, '
  'убирал пробелы по краям и повторы внутри вакансии, затем считал неупорядоченные пары.')
p('Запустил два отдельных процесса A и B. Лидера выбирает Kazoo Lock на эфемерных '
  'последовательных узлах. Для обоих клиентов сервер подтвердил тайм-аут сессии 10 секунд. '
  'При получении лидерства координатор увеличивает эпоху.')
p('Через каждые 10 000 строк координатор сохраняет в S3 счётчики пар, список учтённых вакансий '
  'и позицию в CSV. В ZooKeeper хранится ссылка на чекпоинт и его SHA-256. '
  'Запасной процесс загружает счётчики, пропускает уже учтённые строки и считает оставшуюся часть. '
  'В обоих опытах он восстановился с 20 000 строк и 5800 уникальных пар.')
p('Лидера приостанавливал средствами ОС. Возобновлял A после завершения B, '
  'выдержав паузу не меньше 40 секунд. '
  'Между пакетами по 1000 строк добавлена задержка 30 мс, чтобы расчёт не успел закончиться до паузы.')
page()

# 5. Unsafe experiment.
h('5. Приостановка без защиты: FENCING=0')
p(f'После чекпоинта на 20 000 строк приостановил A. Через {dec(unsafe["failover_seconds"])} с '
  'B стал лидером эпохи 2, восстановил состояние и записал результат. '
  f'Через {dec(unsafe["pause_seconds"])} с возобновил A: он завершил свой расчёт и тоже записал результат.')
screen('unsafe', 'Рисунок 4. Две успешные публикации: сначала B, затем возобновлённый A')
screen('unsafe-pointer', 'Рисунок 5. get -s: указатель версии 2 перезаписан координатором A, эпоха 1')
p('B увеличил версию указателя с 0 до 1. Возобновлённый A повысил её до 2 '
  'и вернул указатель на старую эпоху.')
page()

# 6. Fenced experiment.
h('6. Приостановка с защитой: FENCING=1')
p('Повторил опыт с проверкой эпохи при публикации указателя. Проверка версии узла epoch '
  'и изменение узла result выполняются одной транзакцией ZooKeeper. '
  'После получения лидерства B эпоха стала равна 2, поэтому токен A из эпохи 1 устарел.')
screen('fenced', 'Рисунок 6. После возобновления A сервер отклонил его запись с BadVersionError')
screen('fenced-pointer', 'Рисунок 7. get -s: версия указателя осталась 1, автор B, эпоха 2')
p('A не смог заменить указатель B. Файлы эпох в S3 имеют разные имена; '
  'опубликованным считается файл из узла result.')
page()

# 7. Verification and timings.
h('7. Сверка результатов и время смены лидера')
p('Сравнил результаты A и B в обоих опытах с файлом skills_2.csv из работы 3. '
  'Совпали все ключи, частоты и байты файлов. Дополнительно скачал из S3 файл '
  'по каждому итоговому указателю и получил то же содержимое.')
table(['Показатель', 'Работа 3', 'FENCING=0', 'FENCING=1'],
      [['Строк CSV', '229 388', '229 388', '229 388'],
       ['Вакансий 1С', '18 164', '18 164', '18 164'],
       ['Вхождений пар', '214 983', '214 983', '214 983'],
       ['Уникальных пар', '28 430', '28 430', '28 430']], [W-240, 80, 80, 80])
screen('verify', 'Рисунок 8. Проверка четырёх результатов, всех частот и чтения из S3')
p('Время считал по монотонным часам: t смены = t получения лидерства B - t приостановки A. '
  'Начальная отметка сделана сразу после остановки вычисляющего процесса средствами ОС.')
table(['Измерение', 'Без защиты', 'С защитой'],
      [['Смена лидера', dec(unsafe['failover_seconds']) + ' с', dec(safe['failover_seconds']) + ' с'],
       ['Пауза A', dec(unsafe['pause_seconds']) + ' с', dec(safe['pause_seconds']) + ' с'],
       ['Принятых публикаций', 2, 1],
       ['Итоговый указатель', 'версия 2, автор A', 'версия 1, автор B']], [W-220, 110, 110])
page()

# 8. Answers and repository.
h('8. Ответы на вопросы')
sub('Почему три сервера, а не два или четыре?')
p('ZooKeeper нужна работающая большая часть ансамбля. Кворум равен floor(N/2) + 1. '
  'При двух серверах нужны оба: потеря любого из них сразу останавливает запись. '
  'У трёх серверов достаточно двух, поэтому один можно потерять. '
  'Четвёртый сервер не даёт ещё одного допустимого отказа: для кворума всё равно нужны три.')
table(['Серверов N', 'Кворум', 'Допустимо отказов'],
      [[2, 2, 0], [3, 2, 1], [4, 3, 1], [5, 3, 2]], [W/3]*3)
p('Если требуется пережить два отказа, нужен ансамбль из пяти серверов. '
  'Размещать их тогда надо на разных машинах, иначе отказ одного ПК остановит весь ансамбль.')
sub('Почему эпоху проверяет получатель записи, а не ZooKeeper?')
p('ZooKeeper может завершить старую сессию и выбрать нового лидера, но он не останавливает '
  'вычисляющий процесс. После паузы старый лидер продолжает выполнение с того места, '
  'на котором остановился, и может отправить запись со старой эпохой. Именно это произошло с A.')
p('Поэтому получатель должен проверять эпоху в момент принятия записи. В моей реализации '
  'получатель публикует указатель в ZooKeeper и явно использует его проверку версии: '
  'check(epoch) и set_data(result) входят в одну транзакцию. Сам ZooKeeper умеет выполнить '
  'такую проверку, но приложение должно её запросить. Произвольную запись напрямую в S3 '
  'или другую базу он автоматически не защищает.')
sub('Вывод')
p('Ансамбль продолжил работу при потере одного сервера и потерял кворум при потере двух. '
  'Чекпоинт позволил запасному координатору завершить расчёт с теми же данными. '
  'Без fencing старый лидер повторно опубликовал результат, а с проверкой эпохи '
  'его запись была отклонена и указатель запасного координатора сохранился.')
p('Конфигурации, код, журналы запусков и отчёт: '
  f'<link href="{REPO}" color="#245a88">github.com/IGK-arch/itmo-zookeeper-1c</link>.')


def footer(canvas, doc):
    if doc.page > 1:
        canvas.saveState()
        canvas.setFont('Times', 10)
        canvas.drawCentredString(A4[0]/2, 10*mm, str(doc.page))
        canvas.restoreState()


doc = SimpleDocTemplate(str(OUT), pagesize=A4, leftMargin=18*mm, rightMargin=18*mm,
                        topMargin=16*mm, bottomMargin=17*mm,
                        title='Лабораторная работа 4. Apache ZooKeeper',
                        author='Карташов Игорь Олегович, J3312')
doc.build(story, onFirstPage=footer, onLaterPages=footer)
(ROOT / 'evidence/pdf-screen-regions.json').write_text(json.dumps(views, ensure_ascii=False, indent=2), encoding='utf-8')
print(OUT)
print('Screenshots:', len(views), '; distinct originals:', len({v['sha256'] for v in views}))
