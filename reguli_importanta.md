# Regulile lui Jarvis

Aici reglezi cand te suna Jarvis. Programul citeste fisierul la fiecare verificare,
deci o schimbare se aplica singura, fara repornire.

Cum se editeaza: liniile care incep cu `-` si au forma `nume: valoare` sunt regulile.
Schimba doar ce e dupa doua puncte; numele regulii ramane neschimbat.
Restul textului e doar explicatie.

Daca gresesti ceva, Jarvis scrie in jurnal ce regula e gresita si la ce linie,
si nu suna pana nu e reparat fisierul.

## Evenimente importante

Un eveniment e important daca are aceasta culoare in Google Calendar.
Culori posibile: Tomato, Flamingo, Tangerine, Banana, Sage, Basil, Peacock,
Blueberry, Lavender, Grape, Graphite.

- culoare eveniment important: Tomato

Cu cate minute inainte de eveniment te suna.
Trebuie sa fie mai mare decat intervalul de verificare de mai jos.

- minute inainte de eveniment: 30

## Verificare

La cate minute se uita Jarvis in calendar.

- minute intre verificari: 15

Ce calendare urmareste. `principal` este calendarul tau de baza.
Pentru mai multe, desparte-le cu virgula.

- calendare: principal

## Evenimente de o zi intreaga

Pentru un eveniment important fara ora (de o zi intreaga), un singur apel in ziua
respectiva, la aceasta ora.

- ora apel pentru zi intreaga: 09:00

## Zile de nastere

Zilele de nastere din calendar (cele puse de Google din contacte) nu au nevoie de
culoare. Un singur apel pentru toate zilele de nastere din aceeasi zi.
Scrie `da` sau `nu`.

- apel pentru zile de nastere: da
- ora apel pentru zile de nastere: 18:00

## Ore de liniste

In acest interval Jarvis nu suna. Nu se pierde nimic: tot ce ar fi trebuit anuntat
in timpul orelor de liniste se spune intr-un singur apel, imediat ce se termina.
Scrie intervalul ca `HH:MM-HH:MM`, sau `nu` daca vrei apeluri la orice ora.

- ore de liniste: 23:00-07:00

## Limita de apeluri

Cel mult un apel la atatea minute. Un apel care pica prea devreme se amana.

- minute intre apeluri: 15

Cate apeluri cel mult intr-o zi (zilele de nastere se numara si ele).

- apeluri pe zi: 10

## Daca nu raspunzi

O singura reincercare, dupa atatea minute. Nu se numara la limitele de mai sus.
Scrie `da` sau `nu`.

- reincercare daca nu raspund: da
- minute pana la reincercare: 5

## Emailuri

Scrie `da` ca Jarvis sa urmareasca si emailurile din Gmail, sau `nu` ca sa le ignore.

- apel pentru emailuri: da

Cum sunt tratate emailurile:
1. Cele de la expeditorii urgenti de mai jos: apel imediat, fara AI.
2. Reclamele si tot ce e trimis automat de un sistem (coduri, confirmari, plati,
   livrari, newslettere): ignorate pe loc. Nu ajung la AI.
3. Cele care par scrise de un om: le citeste Claude si decide dupa descrierea de mai jos.

Expeditori urgenti. Suna imediat, si in orele de liniste, si peste limita de apeluri.
Scrie adresa, apoi optional `|` si cu ce trebuie sa inceapa subiectul.
Pentru mai multi, desparte-i cu virgula. Scrie `nu` daca nu vrei niciunul.

- expeditori urgenti: noreply@dronework.example | Work available

Ce inseamna important pentru emailurile scrise de oameni. E instructiunea pentru Claude:
scrie-o in cuvintele tale, pe un singur rand.

- ce e important la email: mesaje de business si emailuri personale care imi cer un raspuns sau o actiune, mai ales oferte de lucru, clienti si lucruri cu termen apropiat
