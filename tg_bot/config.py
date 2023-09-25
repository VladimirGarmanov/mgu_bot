from dataclasses import dataclass
from typing import List
from environs import Env

@dataclass
class TgBot:
    token: str
    #admin: List[int]
    #use_redis: bool
@dataclass
class DbConfig:
    host: str
    password: str
    user: str
    database: str
@dataclass
class Miscellaneous:
    other_params: str = None

@dataclass
class Config:
    tg_bot: TgBot
    #db: DbConfig
    #misc: Miscellaneous
def load_config(path: str=None):
    env = Env()
    env.read_env(path=path)
    return Config(
        tg_bot=TgBot(
            token=env.str("BOT_TOKEN"),
            #admin=map(int,env.list("ADMIN_IDS")),
            #use_redis=env.bool("USER_REDIS")
                     ),
        #db=DbConfig(
        #    host=env.str("DB_HOST"),
        #    password=env.str('DB_PASSWORD'),
        #    user=env.str("DB_USER"),
        #    database=env.str("DB_NAME")

#        ),
#        misc=Miscellaneous()
        )