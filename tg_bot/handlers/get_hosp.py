from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import Command
router = Router()
hosp = ['1) Документ, удостоверяющий личность (паспорт или его заменяющий документ);',
        "2)Полис медицинского страхования (обязательного или добровольного);","3) СНИЛС;",
        "4) Анализ ПЦР на коронавирусную инфекцию сроком давности не более 48 часов, ВКЛЮЧАЯ день взятия мазка;",
        "5) Анализ крови на сифилис методом ИФА — действительные в течение 3 месяцев","6) Анализ крови на антитела к ВИЧ — действительные в течение 3 месяцев",
        "7) Анализ крови на HBsAg и анти-HCV) — действительные в течение 3 месяцев;","8) Анализ группы крови и резус-фактора — бессрочные;",
        "9) Общий анализ крови (гемоглобин, тромбоциты, лейкоциты с лейкоцитарной формулой, СОЭ) — действителен в течение 14 дней;",
        "10) Биохимический анализ крови (калий, натрий, креатинин, глюкоза, общий белок,билирубин, АСТ, АЛТ, СРБ) — действителен в течение 14 дней;",
        "11) Общий анализ мочи — действителен в течение 14 дней;","12) Коагулограмма — действительна в течение 14 дней;",
        "13) Рентген органов грудной клетки или компьютерная томография органов грудной клетки — действительные в течение 3 месяцев;",
        "14) ЭКГ — действительна в течение 14 дней;","15) УЗДГ сосудов нижних конечностей — действительна в течение 30 дней;",
        "16) Эхо-КГ (для пациентов старше 60 лет ИЛИ с установленным диагнозом фибрилляция предсердий, перенёсших в анамнезе острое нарушение мозгового кровообращения,инфаркт миокарда) — действительно в течение 3 месяцев;",
        "17) Заключение терапевта, с прописанным осмотром по системам органов, сопутствующими диагнозами и всей принимаемой терапией с рекомендациями по еёкоррекции перед операцией – действительно в течение 14 дней;",
        "18) Заключение инфекциониста ТОЛЬКО при наличии антител на ВИЧ, сифилис или гепатиты."]
@router.message(Command('get_hosp'))
async def start(message: Message):
    await message.answer("Отправляю список анализов")
    for i in hosp:
        await message.answer(text=i)


#def register_start(dp: Dispatcher):