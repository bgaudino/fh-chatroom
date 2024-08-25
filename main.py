import asyncio
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from fasthtml import common as fh

from starlette.middleware.base import BaseHTTPMiddleware
from random_username.generate import generate_username


TIMEZONE = 'America/Chicago'


@dataclass
class Message:
    id: int
    user: str
    content: str
    timestamp: datetime

    def __ft__(self, **kwargs):
        return fh.P(
            fh.Strong(f'{self.user}:'),
            self.content,
            **kwargs,
        )


db = fh.database('data/chat.db')
messages = db.create(Message)


def get_user(request):
    return request.cookies.get('username')


class GenerateUsernameMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if not get_user(request):
            user = generate_username()[0]
            response = fh.RedirectResponse(request.url)
            response.set_cookie('username', user)
            return response
        return await call_next(request)


middleware = [fh.Middleware(GenerateUsernameMiddleware)]
app = fh.FastHTML(
    hdrs=[fh.picolink, fh.htmxwsscr],
    middleware=middleware,
)

users = set()


def message_input():
    return fh.Group(
        fh.Input(
            name='message',
            autofocus='true',
            placeholder='Say something...',
        ),
        fh.Button('Send'),
        id='message_input',
        hx_swap='outerHTML',
    )


MESSAGE_BATCH_SIZE = 30


def chat_history(last_id=None):
    if last_id is None:
        query = db.query(
            'select * from message order by id desc limit ?',
            [MESSAGE_BATCH_SIZE]
        )
    else:
        query = db.query(
            'select * from message where id < ? order by id desc limit ?',
            [last_id, MESSAGE_BATCH_SIZE]
        )
    if msgs := [Message(**m) for m in query]:
        return (
            *msgs,
            fh.P(
                'loading more messages...',
                id='loading-indicator',
                cls='hx-indicator',
                aria_busy='true',
                hx_get=f'/messages?last_id={msgs[-1].id}',
                hx_trigger='revealed delay:250ms',
                hx_swap='outerHTML',
                hx_indicator='#loading-indicator',
            ),
        )


def connected_users():
    count = len(users)
    return fh.Div(
        f"{count} user{'s' if count > 1 else ''} connected",
        id='users',
        hx_swap_oob='outerHTML',
    )


def current_user(username):
    return fh.P(
        f'You are chatting as {username}',
        fh.A('edit', hx_get='/change_username', hx_target='#username'),
    )


def username_form(current_username):
    return fh.Form(
        fh.Label('Username', _for='new_username'),
        fh.Group(
            fh.Input(id='new_username', value=current_username),
            fh.Button(
                'Cancel',
                cls='secondary',
                type='button',
                hx_get='/username',
                hx_target='#username',
            ),
            fh.Button('Save'),
        ),
        hx_post='/change_username',
        hx_target='#username',
    )


@app.get('/')
def home(username: str):
    return fh.Titled(
        'Chatroom',
        fh.Div(
            connected_users(),
            fh.Div(
                current_user(username),
                id='username',
            ),
            fh.Form(
                message_input(),
                hx_ext='ws',
                ws_connect='/chat',
                ws_send='true',
            ),
            fh.Div(
                chat_history(),
                id='chat-history',
            )
        ),
    )


@app.get('/messages')
def get_messages(last_id: int):
    return chat_history(last_id)


@app.get('/username')
def get_username(username: str):
    return current_user(username)


@app.get('/change_username')
def get_username_form(username: str):
    return username_form(username)


@app.post('/change_username')
def change_username(new_username: str):
    response = fh.Response(headers={'HX-Redirect': '/'})
    response.set_cookie('username', new_username)
    return response


async def on_connect(send):
    users.add(send)
    await send(chat_history())
    asyncio.create_task(update_users())


async def on_disconnect(send):
    users.discard(send)
    asyncio.create_task(update_users())


@app.ws('/chat', conn=on_connect, disconn=on_disconnect)
async def chat(message: str, send, ws):
    user = get_user(ws)
    message = Message(
        user=user,
        content=message,
        timestamp=datetime.now(tz=ZoneInfo('America/Chicago')),
    )
    message = messages.insert(message)
    asyncio.create_task(update_chat(message))


async def update_chat(message):
    to_discard = set()
    for send in users:
        try:
            await send(fh.Div(message, id='chat-history', hx_swap_oob='afterbegin'))
        except Exception:
            to_discard.add(send)
    if to_discard:
        users.difference_update(to_discard)
        asyncio.create_task(update_users())


async def update_users():
    to_discard = set()
    for send in users:
        try:
            await send(connected_users())
        except Exception:
            to_discard.add(send)
    if to_discard:
        users.difference_update(to_discard)
        asyncio.create_task(update_users())

fh.serve(port=8000)
