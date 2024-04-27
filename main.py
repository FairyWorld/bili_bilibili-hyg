# -*- coding: UTF-8 -*-
# Copyright (c) 2023 ZianTT
# bilibili-hyg is licensed under Mulan PubL v2.
# You can use this software according to the terms and conditions of the Mulan PubL v2.
# You may obtain a copy of Mulan PubL v2 at:
#          http://license.coscl.org.cn/MulanPubL-2.0
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND,
# EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT,
# MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
# See the Mulan PubL v2 for more details.
import base64
import hashlib
import json
import os
import random
import socket
import sys
import time
import requests
import sentry
sentry_sdk = sentry.init()
from loguru import logger
import qrcode
import urllib.parse
import threading
import uvicorn

from functools import reduce
from hashlib import md5
from Crypto.Cipher import PKCS1_v1_5
from Crypto.PublicKey import RSA
import hmac

import json
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

import wmi

logger.remove()
handler_id = logger.add(sys.stderr, format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>", level="INFO")

def login():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) BHYG/0.6.3"
        }
    def cookie(cookies):
        lst = []
        for item in cookies.items():
            lst.append(f"{item[0]}={item[1]}")

        cookie_str = ';'.join(lst)
        return cookie_str

    def getCookies(cookie_jar, domain):
        cookie_dict = cookie_jar.get_dict(domain=domain)
        found = ['%s=%s' % (name, value) for (name, value) in cookie_dict.items()]
        return ';'.join(found)

    def qr_login(session):
        generate = session.get("https://passport.bilibili.com/x/passport-login/web/qrcode/generate", headers=headers)
        generate = generate.json()
        if generate['code'] == 0:
            url = generate['data']['url']
        else:
            logger.error(generate)
            return
        qr = qrcode.QRCode()
        qr.add_data(url)
        qr.print_ascii(invert=True)
        img=qr.make_image()
        img.show()
        logger.info("请使用Bilibili手机客户端扫描二维码")
        while True:
            time.sleep(1)
            url = "https://passport.bilibili.com/x/passport-login/web/qrcode/poll?source=main-fe-header&qrcode_key="+generate['data']['qrcode_key']
            req = session.get(url, headers=headers)
            # read as utf-8
            check = req.json()["data"]
            if check['code'] == 0:
                logger.success("登录成功")
                cookies = requests.utils.dict_from_cookiejar(session.cookies)
                break
            elif check['code'] == 86101:
                pass
            elif check['code'] == 86090:
                logger.info(check["message"])
            elif check['code'] == 86083:
                logger.error(check["message"])
                return qr_login(session)
            elif check['code'] == 86038:
                logger.error(check["message"])
                return qr_login(session)
            else:
                logger.error(check)
                return qr_login(session)
        return cookie(cookies)

    def verify(gt,challenge,token):
            pending_captcha = {
                "gt": gt,
                "challenge": challenge,
                "token": token
            }
            with open("data/toc", "w") as f:
                f.write(json.dumps({"type":"geetest","data":pending_captcha}))
            with open("data/tos", "a+") as f:
                while True:
                    f.seek(0,0)
                    data = f.read()
                    if data != "":
                        captcha_data = json.loads(data)
                        if captcha_data["success"] == False:
                            f.truncate(0)
                            return False
                        f.truncate(0)
                        return captcha_data

    def verify_code_login(session):
        #https://passport.bilibili.com/x/passport-login/captcha
        captcha = session.get("https://passport.bilibili.com/x/passport-login/captcha", headers=headers).json()
        gt = captcha["data"]["geetest"]["gt"]
        challenge = captcha["data"]["geetest"]["challenge"]
        token = captcha["data"]["token"]
        tel = input('请输入手机号（非大陆手机号请添加国家号，如+1 4438888888）: ').split(' ')
        if len(tel) == 1:
            cid = "+86"
            tel = tel[0]
        else:
            cid = tel[0]
            tel = tel[1]
        logger.info("请完成验证")
        cap_data = verify(gt,challenge,token)
        while cap_data == False:
            logger.error("验证失败，请重新验证")
            captcha = session.post("https://passport.bilibili.com/x/passport-login/captcha", headers=headers).json()
            gt = captcha["data"]["gee_gt"]
            challenge = captcha["data"]["gee_challenge"]
            token = captcha["data"]["recaptcha_token"]
            cap_data = verify(gt,challenge,token)
        logger.success("验证完成")
        data = {
            "cid": cid,
            "tel": tel,
            "token": token,
            "challenge": cap_data["challenge"],
            "validate": cap_data["validate"],
            "seccode": cap_data["seccode"]+"|jordan",
        }
        #https://passport.bilibili.com/x/passport-login/web/sms/send
        send = session.post("https://passport.bilibili.com/x/passport-login/web/sms/send", headers=headers, data=data).json()
        if send["code"] != 0:
            logger.error(f"{send['code']}: {send['message']}")
            return verify_code_login(session)
        else:
            logger.success("验证码发送成功")
            send_token = send["data"]["captcha_key"]
        while True:
            code = input("请输入验证码: ")
            #https://passport.bilibili.com/x/passport-login/web/login/sms
            data = {
                "cid": cid,
                "tel": tel,
                "captcha_key": send_token,
                "code": code
            }
            login = session.post("https://passport.bilibili.com/x/passport-login/web/login/sms", headers=headers, data=data).json()
            if login["code"] != 0:
                logger.error(f"{login['code']}: {login['message']}")
            else:
                logger.success("登录成功")
                cookies = requests.utils.dict_from_cookiejar(session.cookies)
                return cookie(cookies)
        
    def password_login(session):
        from Crypto.Cipher import PKCS1_v1_5
        from Crypto.PublicKey import RSA
        # https://passport.bilibili.com/x/passport-login/web/key
        username = input("请输入用户名: ")
        import getpass
        password = getpass.getpass("请输入密码：")
        captcha = session.get("https://passport.bilibili.com/x/passport-login/captcha", headers=headers).json()
        gt = captcha["data"]["geetest"]["gt"]
        challenge = captcha["data"]["geetest"]["challenge"]
        token = captcha["data"]["token"]
        logger.info("请完成验证")
        cap_data = verify(gt,challenge,token)
        while cap_data == False:
            captcha = session.get("https://passport.bilibili.com/x/passport-login/captcha", headers=headers).json()
            gt = captcha["data"]["geetest"]["gt"]
            challenge = captcha["data"]["geetest"]["challenge"]
            token = captcha["data"]["token"]
            logger.error("验证失败，请重新验证")
            cap_data = verify(gt,challenge,token)
        logger.success("验证完成")
        key = session.get("https://passport.bilibili.com/x/passport-login/web/key", headers=headers).json()["data"]
        rsa_pub=RSA.importKey(key["key"])
        cipher = PKCS1_v1_5.new(rsa_pub)
        enc = base64.b64encode(cipher.encrypt((key["hash"]+password).encode())).decode("utf8")
        data = {
            "username": username,
            "password": enc,
            "token": token,
            "challenge": cap_data["challenge"],
            "validate": cap_data["validate"],
            "seccode": cap_data["seccode"]+"|jordan",
        }
        login = session.post("https://passport.bilibili.com/x/passport-login/web/login", headers=headers, data=data).json()
        if login["code"] != 0:
            logger.error(f"{login['code']}: {login['message']}")
            if login["code"] == -662:
                logger.error("PS: 请求超时，请快一点")
            return password_login(session)
        else:
            if login["data"]["status"] == 2 or login["data"]["status"] == 1:
                logger.warning("需要二次验证")
                # extract tmp_code request_id from login["data"]["url"]
                tmp_token = login["data"]["url"].split("tmp_token=")[1][:32]
                try:
                    scene = login["data"]["url"].split("tmp_token=")[0].split("scene=")[1].split("&")[0]
                except IndexError:
                    scene = "loginTelCheck"
                info = session.get("https://passport.bilibili.com/x/safecenter/user/info?tmp_code="+tmp_token, headers=headers).json()
                if info["data"]["account_info"]["bind_tel"]:
                    logger.info("已绑定手机号")
                    tel = info["data"]["account_info"]["hide_tel"]
                    logger.info("即将给该手机号发送验证码: "+tel)
                captcha = session.post("https://passport.bilibili.com/x/safecenter/captcha/pre", headers=headers).json()
                gt = captcha["data"]["gee_gt"]
                challenge = captcha["data"]["gee_challenge"]
                token = captcha["data"]["recaptcha_token"]
                logger.info("请完成验证")
                cap_data = verify(gt,challenge,token)
                while cap_data == False:
                    logger.error("验证失败，请重新验证")
                    captcha = session.post("https://passport.bilibili.com/x/safecenter/captcha/pre", headers=headers).json()
                    gt = captcha["data"]["gee_gt"]
                    challenge = captcha["data"]["gee_challenge"]
                    token = captcha["data"]["recaptcha_token"]
                    cap_data = verify(gt,challenge,token)
                logger.success("验证完成")
                data={
                    "recaptcha_token": token,
                    "gee_challenge": cap_data["challenge"],
                    "gee_validate": cap_data["validate"],
                    "gee_seccode": cap_data["seccode"]+"|jordan",
                    "sms_type": scene,
                    "tmp_code": tmp_token
                }
                # https://passport.bilibili.com/x/safecenter/common/sms/send
                send = session.post("https://passport.bilibili.com/x/safecenter/common/sms/send", headers=headers, data=data).json()
                if send["code"] != 0:
                    logger.error(f"{send['code']}: {send['message']}")
                    return password_login(session)
                else:
                    logger.success("验证码发送成功")
                    send_token = send["data"]["captcha_key"]
                while True:
                    code = input("请输入验证码: ")
                    data = {
                        "type": "loginTelCheck",
                        "tmp_code": tmp_token,
                        "captcha_key": send_token,
                        "code": code,
                    }
                    url = "https://passport.bilibili.com/x/safecenter/login/tel/verify"
                    if login["data"]["status"] == 1:
                        del data["type"]
                        data["verify_type"] = "sms"
                        url = "https://passport.bilibili.com/x/safecenter/sec/verify"
                    send = session.post(url, headers=headers, data=data).json()
                    if send["code"] != 0:
                        logger.error(f"{send['code']}: {send['message']}")
                    else:
                        logger.success("登录成功")
                        code = send["data"]["code"]
                        data = {
                            "source": "risk",
                            "code": code
                        }
                        session.post("https://passport.bilibili.com/x/passport-login/web/exchange_cookie", headers=headers, data=data).json()
                        cookies = requests.utils.dict_from_cookiejar(session.cookies)
                        return cookie(cookies)
            logger.success("登录成功")
            cookies = requests.utils.dict_from_cookiejar(session.cookies)
            return cookie(cookies)

    session = requests.session()
    session.get("https://www.bilibili.com/", headers=headers)

    logger.info("请选择登录方式\n1. cookie登录\n2. 扫码登录\n3. 用户名密码登录\n4. 验证码登录")
    method = input("请输入数字: ")
    if method == '1':
        cookie_str = input("请输入cookie: ")
    elif method == '2':
        cookie_str = qr_login(session)
    elif method == '3':
        cookie_str = password_login(session)
    elif method == '4':
        cookie_str = verify_code_login(session)
    else:
        logger.error("暂不支持此方式")
        login()
    
    logger.debug('=' * 20)
    logger.debug(cookie_str)
    logger.debug('=' * 20)
    return cookie_str

uid = ""

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/", response_class=HTMLResponse)
def main_page():
    # 返回html
    return html

@app.get("/api")
def get(data: str| None = None):
    if data:
        with open("data/tos", "w+") as f:
            f.write(data)
        return "OK"
    with open("data/toc", "a+") as f:
        f.seek(0,0)
        data = f.read()
        if data == '':
            return {}
        else:
            f.truncate(0)
            return json.loads(data)

def get_machine_code():
    m_wmi = wmi.WMI()
    cpu_info = m_wmi.Win32_Processor()
    if len(cpu_info) > 0:
        cpu_serial = cpu_info[0].ProcessorId
        if cpu_serial == None:
            cpu_serial = ''
    board_info = m_wmi.Win32_BaseBoard()
    if len(board_info) > 0:
        board_serial = board_info[0].SerialNumber.strip().strip('.')
        if board_serial == None:
            board_serial = ''
    combine_str = cpu_serial + board_serial + 'bhyg-salt'
    if combine_str == '':
        logger.error("环境异常！")
        sys.exit()
    combine_byte = combine_str.encode("utf-8")
    machine_code = hashlib.md5(combine_byte).hexdigest()
    return machine_code

def verify(key):
    global uid
    try:
        rsa_priv = """-----BEGIN RSA PRIVATE KEY-----
    MIIEogIBAAKCAQEAkazjBRGNcYV/RfTjOgach54ueXHZlDHWqVyLxuVjfeOYbzNt
    k+tmd0nZweBCmFnrVM/MSAfU3fjI2XuFRP00Jjnevct0f3uj4BmkCH1RehjQgPlg
    Xrspb+cEbulMPFlxLrOB61TvInDEn0lbyiN4ini7ALEzKj36usTCR8yTy3IrVHFe
    6Z1zggCuu/up/hGZEDxtNXtyLDEnMrutq7sEQvFIhfSQ4ng6Vgf0SJetOKEazdie
    SBPGRqihfT8Mppng1o3AOQkegqqo6vRYmAMwuBZWi0xUteX8KnjzSqr6O8z1X+iq
    FZ6RJpWLbyDlHkqo6Jd4rzl1OR02E7b9X5S/hQIDAQABAoIBAAOJVe2Okod5/S/+
    lPGYrX4hWfF60RRm7VYpN/95HCQ3PUEd14Aqy88DjPTG8/bs3+isLsJk5kcJPh8B
    f6fAGd7/sqea49Ygc0cCeFf4atzy80TeSPejxYrA6fujUEV6ymOe2f2Tj0afxDY1
    urO6jreV3LxUkPBqlsan9it2DPR4ZLA7JSacauqkag0gq5m0+IQO/8brmiT2A5m6
    tOKF++8lpniHYuehI7Pv10Fhv3FmOngeuA5yIMOc5Id7I3jM/lgDlzG2kUlpJAp0
    cxYEUW9iI0Se38d0SVHjm6VUb8IA9C/PGbxKN7V70Jw+NLl9U/gYnFmpTveXdO2t
    PbuPWdUCgYEAuM4gzcMJkRAz13HmJGCGR+gDVih9kS8unaudwGeP5MIKkpzKhNJe
    Z+osntGMpQPopUmEhePkwGJZrNFgShEJNDu84jk9/5ATde76JxXH0296InEqGTiX
    TCNgglWJ5hrCE5Vlr1NZ8yQuN3CkgnhCb7Au+Nj6kfg5y0KO/91U/a8CgYEAycux
    DHF3zVs4X/i1/PI/0RJq/z/wB9Y0z2bi783DbTMXCylja6NSaDYwGZKOrjx/Mq9r
    uE3y+L1DgjUs97FTqv6WbNWDhKSkza3cBGFXnGgOLi/+cndX5UJR9Y2na5cxd/Qj
    zAiXUpfM2BZ9hFOj5+UggMIv+7okgAj2hsr29wsCgYArGrkABTvYAAV3fPOHDJSF
    dRJCKFORZ4Xh9MNouz8OxkudAsEh1cd7SV169bluS8kZtFoauJsEXGw6KOPiorKY
    4k4eHefeEgbX/ROPxj7DjD7ahbaiB1cSxTWfcMAnUZpu4uvCxxg14/x7peRZIh+s
    2VU7abCYF2OziyS7fS5ztQKBgEoZSrT4AXbd1TCggisUxUw/SBzcXIZ0KMYz0Icf
    9m/lv8NwejpvKXZs13K8dzoRqt9wvMxbiym9TcnFPvLhIYj7nT7vlDCjyIRiIBVX
    rTUYnIRnSTa9DgB4PuI9FsoSJa8XbgGg8ff5F9YNRB/QGrKvVyUQqU/1BSwinmvW
    oaMLAoGAJx726lHlcJASjwsLIE3EW+ijV8iQx0r/ArjeDvRHJgSBWb9jlvyEYZGR
    9QaYcxiykhiYt9Ktd3xaqeU5v28dHeWeFtpCgE6/ImthMI+E48/SQBQmdhOYmyLR
    9RDkLEYVnTl6fjl5DKEXUcwEWuKD+J+qzud8kw2BRu9csB9hm/Q=
    -----END RSA PRIVATE KEY-----"""
        cipher = PKCS1_v1_5.new(RSA.importKey(rsa_priv))
        data = json.loads(cipher.decrypt(base64.b64decode(key), 0).decode('utf-8'))
        logger.info(f"欢迎用户{data['user']}! 距离授权过期还有{int((data['expire']-time.time())/86400)}天")
        sentry_sdk.set_user({"username": data["user"]})
        if "uid" in data:
            uid = data["uid"]
        if data["machine_code"] != get_machine_code():
            logger.error("机器码不正确")
            logger.warning("PS: 机器码在0.6.1版本更换了新算法，请联系分发人提供新的激活码或授权码")
            return False
        if time.time() > data["expire"]:
            logger.error("授权已过期")
            return False
        return True
    except:
        logger.error("授权错误")
        return False

class HygException(Exception):
        pass

class BilibiliHyg:
        def __init__(self, config):
            self.config = config
            self.config["gaia_vtoken"] = None
            self.session = requests.Session()
            self.headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) BHYG/0.6.3",
            }
            
            self.headers["Cookie"] = self.config["cookie"]

            if "co_delay" not in self.config:
                co_delay = input("请输入创建订单时间间隔(该选项影响412风控概率，单开建议使用0)(秒)：")
                try:
                    self.config["co_delay"] = float(co_delay)
                except:
                    logger.warning("未设置时间间隔，默认为0")
                    self.config["co_delay"] = 0
                while(self.config["co_delay"] < 0):
                    logger.error("时间间隔过短")
                    self.config["co_delay"] = float(input("请输入创建订单时间间隔(该选项影响412风控概率，单开建议使用0)(秒)："))
            if "status_delay" not in self.config:
                try:
                    self.config["status_delay"] = float(input("请输入票务信息检测时间间隔(该选项影响412风控概率)(秒)："))
                except:
                    logger.warning("未设置时间间隔，默认为0.2")
                    self.config["status_delay"] = 0.2
                while(self.config["status_delay"] < 0):
                    logger.error("时间间隔过短")
                    self.config["status_delay"] = float(input("请输入票务信息检测时间间隔(该选项影响412风控概率)(秒)："))
            
            if "project_id" not in self.config or "screen_id" not in self.config or "sku_id" not in self.config or "pay_money" not in self.config or "id_bind" not in self.config:
                while True:
                    self.config["project_id"] = input("请输入项目id：")
                    url = "https://show.bilibili.com/api/ticket/project/getV2?version=134&id="+self.config["project_id"]
                    response = self.session.get(url, headers=self.headers)
                    if response.status_code == 412:
                            logger.error("被412风控，请联系作者")
                    response = response.json()
                    if(response["errno"] == 3):
                        logger.error("未找到项目ID")
                        continue
                    if(response["data"] == {}):
                        logger.error("服务器无返回")
                        continue
                    if(response["data"]["is_sale"] == 0):
                        logger.error("项目不可售")
                        continue
                    break
                logger.info("项目名称："+response["data"]["name"])
                self.config["id_bind"] = response["data"]["id_bind"]
                self.config["is_paper_ticket"] = response["data"]["has_paper_ticket"]
                screens = response["data"]["screen_list"]
                for i in range(len(screens)):
                    logger.info(str(i)+". "+screens[i]["name"])
                while True:
                    try:
                        screen_id = int(input("请输入场次序号："))
                        if screen_id >= len(screens):
                            raise ValueError
                        break
                    except ValueError:
                        logger.error("序号错误")
                tickets = screens[int(screen_id)]["ticket_list"] # type: ignore
                for i in range(len(tickets)):
                    logger.info(str(i)+". "+tickets[i]["desc"]+" "+str(tickets[i]["price"]/100)+"元")
                while True:
                    try:
                        sku_id = int(input("请输入票档序号："))
                        if sku_id >= len(tickets):
                            raise ValueError
                        break
                    except ValueError:
                        logger.error("序号错误")
                self.config["screen_id"] = str(screens[int(screen_id)]["id"])
                self.config["sku_id"] = str(tickets[int(sku_id)]["id"])
                self.config["pay_money"] = str(tickets[int(sku_id)]["price"])
                self.config["ticket_desc"] = str(tickets[int(sku_id)]["desc"])
                if self.config["is_paper_ticket"]:
                    if response["data"]["express_free_flag"]:
                        self.config["express_fee"] = 0
                    else:
                        self.config["express_fee"] = response["data"]["express_fee"]
                    url = "https://show.bilibili.com/api/ticket/addr/list"
                    resp_ticket = self.session.get(url, headers=self.headers)
                    if(resp_ticket.status_code == 412):
                        logger.error("被412风控，请联系作者")
                    addr_list = resp_ticket.json()["data"]["addr_list"]
                    if len(addr_list) == 0:
                        logger.error("没有收货地址，请先添加收货地址")
                    else:
                        for i in range(len(addr_list)):
                            logger.info(f"{str(i)}. {addr_list[i]['prov']+addr_list[i]['city']+addr_list[i]['area']+addr_list[i]['addr']} {addr_list[i]['name']} {addr_list[i]['phone']}")
                        while True:
                            try:
                                addr_index = int(input("请选择收货地址序号："))
                                if addr_index >= len(addr_list):
                                    raise ValueError
                                break
                            except ValueError:
                                logger.error("序号错误")
                        addr = addr_list[addr_index]
                        self.config["deliver_info"] = json.dumps({
                            "name" : addr["name"],
                            "tel" : addr["phone"],
                            "addr_id" : addr["addr"],
                            "addr" : addr["prov"]+addr["city"]+addr["area"]+addr["addr"],
                        },ensure_ascii=False)
                logger.debug("您的screen_id 和 sku_id 和 pay_money 分别为："+self.config["screen_id"]+" "+self.config["sku_id"]+" "+self.config["pay_money"])
            self.token = ""
            if self.config["id_bind"] != 0 and ("buyer_info" not in self.config):
                url = "https://show.bilibili.com/api/ticket/buyer/list"
                response = self.session.get(url, headers=self.headers)
                if response.status_code == 412:
                    logger.error("被412风控，请联系作者")
                buyer_infos = response.json()["data"]["list"]
                self.config["buyer_info"] = []
                if len(buyer_infos) == 0:
                    logger.error("未找到购票人，请前往实名添加购票人")
                else:
                    multiselect = True
                    if(self.config["id_bind"] == 1):
                        logger.info("本项目只能购买一人票")
                        multiselect = False
                    while True:
                        try:
                            if multiselect:
                                for i in range(len(buyer_infos)):
                                    logger.info(f"{str(i)}. {buyer_infos[i]['name']} {buyer_infos[i]['personal_id']} {buyer_infos[i]['tel']}")
                                buyerids = input("请选择购票人序号(多人用空格隔开)：").split(" ")
                                self.config["buyer_info"] = []
                                for select in buyerids:
                                    self.config["buyer_info"].append(buyer_infos[int(select)]) # type: ignore
                                    logger.info("已选择购票人"+buyer_infos[int(select)]["name"]) # type: ignore
                            else:
                                for i in range(len(buyer_infos)):
                                    logger.info(f"{str(i)}. {buyer_infos[i]['name']} {buyer_infos[i]['personal_id']} {buyer_infos[i]['tel']}")
                                index = int(input("请选择购票人序号："))
                                self.config["buyer_info"].append(buyer_infos[index])
                                logger.info("已选择购票人"+buyer_infos[index]["name"])
                            break
                        except:
                            logger.error("序号错误")
                    if "count" not in self.config:
                        self.config["count"] = len(self.config["buyer_info"])
                    self.config["buyer_info"] = json.dumps(self.config["buyer_info"])
            if self.config["id_bind"] == 0 and ("buyer" not in self.config or "tel" not in self.config):
                logger.info("请添加联系人信息")
                self.config["buyer"] = input("联系人姓名：")
                while True:
                    self.config["tel"] = input("联系人手机号：")
                    if len(self.config["tel"]) == 11:
                        break
                    logger.error("手机号长度错误")
                if "count" not in self.config:
                    self.config["count"] = input("请输入票数：")
            if self.config["is_paper_ticket"]:
                if self.config["express_fee"] == 0:
                    self.config["all_price"] = int(self.config['pay_money'])*int(self.config['count'])
                    logger.info(f"共 {self.config['count']} 张 {self.config['ticket_desc']} 票，单张价格为 {int(self.config['pay_money'])/100}，纸质票，邮费免去，总价为{self.config['all_price'] / 100}")
                else:
                    self.config["all_price"] = int(self.config['pay_money'])*int(self.config['count'])+self.config['express_fee']
                    logger.info(f"共 {self.config['count']} 张 {self.config['ticket_desc']} 票，单张价格为 {int(self.config['pay_money'])/100}，纸质票，邮费为 {self.config['express_fee'] / 100}，总价为{self.config['all_price'] / 100}")
            else:
                self.config["all_price"] = int(self.config['pay_money'])*int(self.config['count'])
                logger.info(f"共 {self.config['count']} 张 {self.config['ticket_desc']} 票，单张价格为 {int(self.config['pay_money'])/100}，总价为{self.config['all_price'] / 100}")
            with open("config.json", "w", encoding="utf-8") as f:
                json.dump(self.config, f)
            sentry_sdk.capture_message('config complete')
            logger.info("准备完毕，获取token中...")
            self.token = self.get_token()
            logger.info("即将开始下单")
            

        def get_ticket_status(self):
            url = "https://show.bilibili.com/api/ticket/project/getV2?version=134&id="+self.config["project_id"]
            try:
                response = self.session.get(url, headers=self.headers, timeout=1)
            except (requests.exceptions.Timeout, requests.exceptions.ReadTimeout, requests.exceptions.ConnectionError):
                logger.error("网络连接超时")
                return -1, 0
            try:
                if response.status_code == 412:
                    logger.error("可能被业务风控\n该种业务风控请及时暂停，否则可能会引起更大问题。")
                    self.risk = True
                    logger.error("暂停30s")
                    logger.error("你也可以尝试更换网络环境，如重启流量（飞行模式开关）重新拨号（重启光猫）等")
                    time.sleep(30)
                    return -1, 0
                screens = response.json()["data"]["screen_list"]
                # 找到 字段id为screen_id的screen
                screen = {}
                for i in range(len(screens)):
                    if screens[i]["id"] == int(self.config["screen_id"]):
                        screen = screens[i]
                        break
                if screen == {}:
                    logger.error("未找到场次")
                    return -1, 0
                # 找到 字段id为sku_id的sku
                skus = screen["ticket_list"]
                sku = {}
                for i in range(len(skus)):
                    if skus[i]["id"] == int(self.config["sku_id"]):
                        sku = skus[i]
                        break
                if sku == {}:
                    logger.error("未找到票档")
                    return -1, 0
                return int(sku["sale_flag_number"]),sku["clickable"]
            except:
                logger.error("可能被风控")
                return -1, 0
        
        def get_prepare(self):
            url = "https://show.bilibili.com/api/ticket/order/prepare?project_id="+self.config["project_id"]
            if self.config["gaia_vtoken"]:
                url += "&gaia_vtoken="+self.config["gaia_vtoken"]
            data = {
                "project_id": self.config["project_id"],
                "screen_id": self.config["screen_id"],
                "order_type": "1",
                "count": self.config["count"],
                "sku_id": self.config["sku_id"],
                "token": "",
                "newRisk": "true",
                "requestSource": "pc-new",
            }
            response = self.session.post(url, headers=self.headers, data=data)
            if response.status_code == 412:
                logger.error("被412风控，请联系作者")
            if(response.json()["errno"] != 0 and response.json()["errno"] != -401):
                logger.error(response.json()["msg"])
            return response.json()["data"]

        def verify(self,gt,challenge,token):
            self.pending_captcha = {
                "gt": gt,
                "challenge": challenge,
                "token": token
            }
            with open("data/toc", "w") as f:
                f.write(json.dumps({"type":"geetest","data":self.pending_captcha}))
            with open("data/tos", "a+") as f:
                while True:
                    f.seek(0,0)
                    data = f.read()
                    if data != "":
                        self.captcha_data = json.loads(data)
                        if self.captcha_data["success"] == False:
                            f.truncate(0)
                            return False
                        self.captcha_data["csrf"] = self.headers["Cookie"][self.headers["Cookie"].index("bili_jct") + 9:self.headers["Cookie"].index("bili_jct") + 41]
                        self.captcha_data["token"] = token
                        success = self.session.post("https://api.bilibili.com/x/gaia-vgate/v1/validate", headers=self.headers, data=self.captcha_data).json()["data"]["is_valid"]
                        self.config["gaia_vtoken"] = token
                        self.captcha_data = None
                        if self.headers["Cookie"].find("x-bili-gaia-vtoken") != -1:
                            self.headers["Cookie"] = self.headers["Cookie"].split("; x-bili-gaia-vtoken")[0]
                        self.headers["Cookie"] += "; x-bili-gaia-vtoken="+ token
                        f.truncate(0)
                        with open("config.json", "w", encoding="utf-8") as f:
                            json.dump(self.config, f)
                        return success

        def get_token(self):
            info = self.get_prepare()
            if(info == {}):
                logger.warning("未开放购票或被风控，请检查配置问题，休息1s")
                time.sleep(1)
                self.get_token()
            if(info["token"]):
                logger.success("成功准备订单"+"https://show.bilibili.com/platform/confirmOrder.html?token="+info["token"])
                sentry_sdk.add_breadcrumb(
                    category='prepare',
                    message=f'Order prepared as token:{info["token"]}',
                    level='info',
                )
                return info["token"]
            else:
                logger.warning("触发风控。")
                logger.warning("类型：验证码 ")
                sentry_sdk.add_breadcrumb(
                    category='gaia',
                    message='Gaia found',
                    level='info',
                )
                riskParam=info["ga_data"]["riskParams"]
                #https://api.bilibili.com/x/gaia-vgate/v1/register
                gtest=self.session.post("https://api.bilibili.com/x/gaia-vgate/v1/register",headers=self.headers, data=riskParam).json()
                while(gtest["code"]!=0):
                    gtest=self.session.post("https://api.bilibili.com/x/gaia-vgate/v1/register",headers=self.headers, data=riskParam).json()
                gt, challenge, token = gtest['data']['geetest']['gt'], gtest['data']['geetest']['challenge'], gtest['data']['token']
                cap_data = self.verify(gt, challenge, token)
                while cap_data == False:
                    logger.error("验证失败，请重新验证")
                    return self.get_token()
                logger.info("验证成功")
                sentry_sdk.add_breadcrumb(
                    category='gaia',
                    message='Gaia passed',
                    level='info',
                )
                return self.get_token()

        def generate_clickPosition(self) -> dict:
            """
            生成虚假的点击事件

            Returns:
                dict: 点击坐标和时间
            """
            # 生成随机的 x 和 y 坐标，以下范围大概是1920x1080屏幕下可能的坐标
            x = random.randint(1320, 1330)
            y = random.randint(880, 890)
            # 生成随机的起始时间和结束时间（或当前时间）
            now_timestamp = int(time.time() * 1000)
            # 添加一些随机时间差 (5s ~ 10s)
            origin_timestamp = now_timestamp - random.randint(5000, 10000)
            return {
                "x": x,
                "y": y,
                "origin": origin_timestamp,
                "now": now_timestamp
            }
        
        def create_order(self):
            url = "https://show.bilibili.com/api/ticket/order/createV2"
            data = {
                "project_id": self.config["project_id"],
                "screen_id": self.config["screen_id"],
                "sku_id": self.config["sku_id"],
                "token": self.token,
                "deviceId": "",
                "project_id": self.config["project_id"],
                "pay_money": self.config["all_price"],
                "count": self.config["count"],
                "timestamp": int(time.time()+5),
                "order_type": "1",
                "newRisk": "true",
                "requestSource": "pc-new",
                "clickPosition": self.generate_clickPosition()
            }
            if self.config["id_bind"] == 0:
                data["buyer"] = self.config["buyer"]
                data["tel"] = self.config["tel"]
            else:
                data["buyer_info"] = self.config["buyer_info"]
            if self.config["is_paper_ticket"]:
                data["deliver_info"] = self.config["deliver_info"]

            response = self.session.post(url, headers=self.headers, data=data)
            if response.status_code == 412:
                logger.error("可能被业务风控\n该种业务风控请及时暂停，否则可能会引起更大问题。")
                self.risk = True
                logger.error("暂停60s")
                time.sleep(60)
                return {}
            return response.json()

        def fake_ticket(self, pay_token):
            url = "https://show.bilibili.com/api/ticket/order/createstatus?project_id="+self.config["project_id"]+"&token="+pay_token+"&timestamp="+str(int(time.time()*1000))
            response = self.session.get(url, headers=self.headers)
            if response.status_code == 412:
                logger.error("被412风控，请联系作者")
            response = response.json()
            if response["errno"] == 0:
                sentry_sdk.add_breadcrumb(
                    category='success',
                    message=f'Success, orderid:{response["data"]["order_id"]}, payurl:https://pay.bilibili.com/payplatform-h5/pccashier.html?params="{urllib.parse.quote(json.dumps(response["data"]["payParam"],ensure_ascii=False))}',
                    level='info',
                )
                logger.success("成功购票")
                order_id = response["data"]["order_id"]
                pay_url = response["data"]["payParam"]["code_url"]
                response["data"]["payParam"].pop("code_url")
                response["data"]["payParam"].pop("expire_time")
                response["data"]["payParam"].pop("pay_type")
                response["data"]["payParam"].pop("use_huabei")
                logger.info("订单号："+order_id)
                self.order_id = order_id
                logger.info("请在微信/支付宝/QQ中扫描以下二维码，完成支付")
                logger.info("二维码内容："+pay_url)
                qr = qrcode.QRCode()
                qr.add_data(pay_url)
                qr.print_ascii(invert=True)
                img = qr.make_image()
                img.show()
                logger.info("或打开 https://pay.bilibili.com/payplatform-h5/pccashier.html?params="+urllib.parse.quote(json.dumps(response["data"]["payParam"],ensure_ascii=False))+" 完成支付")
                logger.info("请手动完成支付")
                return True
            else:
                logger.error("购票失败")
                return False
            
        def order_status(self,order_id):
            url = "https://show.bilibili.com/api/ticket/order/info?order_id="+order_id
            response = self.session.get(url, headers=self.headers)
            if response.status_code == 412:
                logger.error("被412风控，请联系作者")
            response = response.json()
            if response["data"]["status"] == 1:
                return True
            elif response["data"]["status"] == 2:
                logger.success("订单支付成功，祝您游玩愉快！")
                return False
            elif response["data"]["status"] == 4:
                logger.warning("订单已取消")
                return False
            else:
                logger.warning("当前状态未知: "+response["data"]["status_name"]+response["data"]["sub_status_name"])
                return False


        def run(self):
            reset = 0
            while(1):
                self.risk = False
                if self.risk:
                    status = -1
                status, clickable = self.get_ticket_status()
                if(status == 2 or clickable):
                    if(status == 1):
                        logger.warning("未开放购票")
                    elif(status == 3):
                        logger.warning("已停售")
                        if not "ignore" in vars():
                            ignore = input("当前状态可能无法抢票，请确认是否继续抢票，按回车继续")
                    elif(status == 5):
                        logger.warning("不可售")
                        if not "ignore" in vars():
                            ignore = input("当前状态可能无法抢票，请确认是否继续抢票，按回车继续")
                    elif(status == 102):
                        logger.warning("已结束")
                        if not "ignore" in vars():
                            ignore = input("当前状态可能无法抢票，请确认是否继续抢票，按回车继续")
                    for _ in range(50):
                        result = self.create_order()
                        if(result == {}):
                            continue
                        if(result["errno"] == 100009):
                            logger.warning("无票")
                        elif(result["errno"] == 3):
                            logger.warning("慢一点（不用管，仍在全速抢票）")
                        elif(result["errno"] == 100001):
                            logger.warning("小电视速率限制")
                        elif(result["errno"] == 100016):
                            logger.error("项目不可售")
                        elif(result["errno"] == 0):
                            logger.success("成功尝试下单！正在检测是否为假票")
                            pay_token = result["data"]["token"]
                            if(self.fake_ticket(pay_token)):
                                while self.order_status(self.order_id):
                                    logger.info("订单未支付，正在等待")
                                    time.sleep(3)
                                sentry_sdk.capture_message('Exit by in-app exit')
                                return
                            else:
                                logger.error("假票，继续抢票")
                        elif(result["errno"] == 100051):
                            self.token = self.get_token()
                        elif(result["errno"] == 100079 or result["errno"] == 100048):
                            logger.success("已经抢到了啊喂！")
                            sentry_sdk.capture_message('Exit by in-app exit')
                            return
                        else:
                            logger.error("未知错误:"+str(result))
                        time.sleep(self.config["co_delay"])
                        reset += 2
                        time.sleep(self.config["co_delay"])
                        reset += 2
                elif(status == 1):
                    logger.warning("未开放购票")
                elif(status == 3):
                    logger.warning("已停售")
                elif(status == 4):
                    logger.warning("已售罄")
                elif(status == 5):
                    logger.warning("不可售")
                elif(status == 6):
                    logger.error("免费票，程序尚未适配")
                    sentry_sdk.capture_message('Exit by in-app exit')
                    return
                elif(status == 8):
                    logger.warning("暂时售罄，即将放票")
                
                elif(status == -1):
                    continue
                else:
                    logger.error("未知状态:"+str(status))
                time.sleep(self.config["status_delay"])
                reset += 2


def getPort():
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # 绑定到本地主机上随机的端口号
        sock.bind(('localhost', 0))
        # 获取绑定后的端口号
        _, port = sock.getsockname()
        # 关闭socket
        sock.close()
        return port
port = getPort()
html = """<head>
    <script src="https://static.geetest.com/static/js/gt.0.4.9.js"></script>
</head>
<body>
    必要时，这里会出现验证码
    <script>
        function showCaptcha(gt, challenge) {
            initGeetest({
                // 以下配置参数来自服务端 SDK
                product: 'bind',
                gt: gt,
                challenge: challenge,
                offline: false,
                new_captcha: true,
                hideClose:  true,
            }, function (captchaObj) {
                    // 这里可以调用验证实例 captchaObj 的实例方法
                    captchaObj.onReady(function(){
                    //验证码ready之后才能调用verify方法显示验证码
                        captchaObj.verify();
                    });
                    captchaObj.onSuccess(function () {
                        var result = captchaObj.getValidate();
                        data = {
                            success: true,
                            challenge: result.geetest_challenge,
                            validate: result.geetest_validate,
                            seccode: result.geetest_seccode,
                        };
                        fetch("http://127.0.0.1:"""+str(port)+"""/api?data="+JSON.stringify(data))
                        captchaObj.destroy();
                    });
                    captchaObj.onError(function () {
                        data = {
                            success: false
                        };
                        fetch("http://127.0.0.1:"""+str(port)+"""/api?data="+JSON.stringify(data))
                        captchaObj.destroy();
                    });
                    captchaObj.onClose(function () {
                        data = {
                            success: false
                        };
                        fetch("http://127.0.0.1:"""+str(port)+"""/api?data="+JSON.stringify(data))
                        captchaObj.destroy();
                    });
                });
            };
        // 每隔一秒向服务端发送get请求并查看返回值
        setInterval(function() {
            fetch("http://127.0.0.1:"""+str(port)+"""/api")
            .then(response => response.json())
            .then(data => {
                    if (data.type === 'geetest') {
                        showCaptcha(data.data.gt, data.data.challenge)
                    }
            });
        }, 1000);

    </script>
</body>
"""

def main():
    global uid
    try:
            session = requests.session()
            def hmac_sha256(key, message):
                """
                使用HMAC-SHA256算法对给定的消息进行加密
                :param key: 密钥
                :param message: 要加密的消息
                :return: 加密后的哈希值
                """
                # 将密钥和消息转换为字节串
                key = key.encode('utf-8')
                message = message.encode('utf-8')
                # 创建HMAC对象，使用SHA256哈希算法
                hmac_obj = hmac.new(key, message, hashlib.sha256)
                # 计算哈希值
                hash_value = hmac_obj.digest()
                # 将哈希值转换为十六进制字符串
                hash_hex = hash_value.hex()
                return hash_hex
            def gen_bili_ticket():
                o = hmac_sha256("XgwSnGZ1p",f"ts{int(time.time())}")
                url = "https://api.bilibili.com/bapis/bilibili.api.ticket.v1.Ticket/GenWebTicket"
                params = {
                    "key_id":"ec02",
                    "hexsign":o,
                    "context[ts]":f"{int(time.time())}",
                    "csrf": ''
                }

                headers = {
                        'user-agent': "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0"
                    }
                resp = requests.post(url, params=params,headers=headers).json()
                return resp["data"]["ticket"]
            def get_space_info(uid, session):
                headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) BHYG/0.6.3",
                        'Referer': 'https://www.bilibili.com/',
                    }
                mixinKeyEncTab = [
                    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
                    33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40,
                    61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11,
                    36, 20, 34, 44, 52
                ]
                session.get('https://api.bilibili.com/x/web-interface/nav', headers=headers)
                def getMixinKey(orig: str):
                    '对 imgKey 和 subKey 进行字符顺序打乱编码'
                    return reduce(lambda s, i: s + orig[i], mixinKeyEncTab, '')[:32]
                def encWbi(params: dict, img_key: str, sub_key: str):
                    '为请求参数进行 wbi 签名'
                    mixin_key = getMixinKey(img_key + sub_key)
                    curr_time = round(time.time())
                    params['wts'] = curr_time                                   # 添加 wts 字段
                    params = dict(sorted(params.items()))                       # 按照 key 重排参数
                    # 过滤 value 中的 "!'()*" 字符
                    params = {
                        k : ''.join(filter(lambda chr: chr not in "!'()*", str(v)))
                        for k, v 
                        in params.items()
                    }
                    query = urllib.parse.urlencode(params)                      # 序列化参数
                    wbi_sign = md5((query + mixin_key).encode()).hexdigest()    # 计算 w_rid
                    params['w_rid'] = wbi_sign
                    return params
                def getWbiKeys() -> tuple[str, str]:
                    '获取最新的 img_key 和 sub_key'
                    headers = {
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) BHYG/0.6.3",
                        'Referer': 'https://www.bilibili.com/'
                    }
                    resp = session.get('https://api.bilibili.com/x/web-interface/nav', headers=headers)
                    resp.raise_for_status()
                    json_content = resp.json()
                    img_url: str = json_content['data']['wbi_img']['img_url']
                    sub_url: str = json_content['data']['wbi_img']['sub_url']
                    img_key = img_url.rsplit('/', 1)[1].split('.')[0]
                    sub_key = sub_url.rsplit('/', 1)[1].split('.')[0]
                    return img_key, sub_key
                img_key, sub_key = getWbiKeys()
                signed_params = encWbi(
                    params={
                        'mid': uid
                    },
                    img_key=img_key,
                    sub_key=sub_key
                )
                query = urllib.parse.urlencode(signed_params)
                data = session.get("https://api.bilibili.com/x/space/wbi/acc/info?"+query, headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0",
                        'Referer': 'https://www.bilibili.com/',
                    }).json()
                if data["code"] == -352:
                    logger.error("被风控，重试中...")
                    time.sleep(2)
                    return get_space_info(uid, session)
                return data
            def get_github_token(session):
                mirror = input("是否使用镜像站点？(Y/n)")
                if mirror.lower() == "n":
                    url_base = "https://github.com"
                else:
                    url_base = "https://kkgithub.com"
                code = session.post(url_base+"/login/device/code",data={"client_id": "0ea323be20ab6b75e944"},headers={"Accept": "application/json"}).json()
                device_code = code["device_code"]
                user_code = code["user_code"]
                verification_uri = code["verification_uri"]
                logger.info(f"请打开 {verification_uri} 并输入 {user_code} 进行验证")
                os.system(f"start {verification_uri}")
                pending = True
                while pending:
                    time.sleep(5)
                    token = session.post(url_base+"/login/oauth/access_token",data={"client_id": "0ea323be20ab6b75e944","device_code":device_code,"grant_type":"urn:ietf:params:oauth:grant-type:device_code"},headers={"Accept":  "application/json"}).json()
                    if "error" in token:
                        if token["error"] == "authorization_pending":
                            continue
                        else:
                            logger.error(token["error_description"])
                            return
                    else:
                        pending = False
                return token["access_token"]
            if not os.path.exists("key"):
                headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) BHYG/0.6.3",
                        'Referer': 'https://www.bilibili.com/',
                    }
                session.get("https://space.bilibili.com/1", headers=headers)
                logger.info("欢迎使用！倒卖狗破解狗414.https://github.com/ZianTT/bilibili-hyg")
                logger.info("无论我开源还是闭源，收费还是免费，这都是我的权利，而不是你的。")
                logger.info("本程序提供个人版激活码，若您确认为个人使用您可以在点击GitHub项目Star后输入您的GitHUb用户名(而非姓名)获取一个免费的7天许可证，到期可再次获取。")
                individual = input("是否为个人使用？(Y/n)")
                if individual.lower() == "n":
                    key = input("本机机器码："+get_machine_code()+"请输入授权码或激活码：")
                    if len(key) == 8:
                        uid = ""
                        logger.info("激活需要绑定您的Bilibili UID，请输入您的UID(若您的激活码为多人版，请随意绑定一个uid)")
                        while True:
                                uid = input("UID:")
                                requests.utils.add_dict_to_cookiejar(session.cookies,{"bilibili_ticket":gen_bili_ticket()})
                                data = get_space_info(uid,session)
                                if data["code"] == -404:
                                    logger.error("UID不存在")
                                    continue
                                name = data["data"]["name"]
                                logger.info(f"UID: {uid} 用户名: {name}")
                                confirm = input("请确认是否为您的账号，一经绑定，无法修改(y/N):")
                                if confirm.lower() != "y":
                                    logger.error("绑定失败")
                                else:
                                    break
                        key = session.get(f"https://bhyg.bitf1a5h.eu.org/activate?code={key}&mc={get_machine_code()}&uid={uid}").json()
                        if key == None:
                            logger.error("激活码无效")
                            logger.info("即将退出")
                            time.sleep(10)
                            return
                    with open("key", "w", encoding="utf-8") as f:
                        f.write(key)
                else:
                    while True:
                        uid = ""
                        logger.info("请确认您已点击Star")
                        gh_token = get_github_token(session)
                        logger.info("激活需要绑定您的Bilibili UID，请输入您的UID(若您的激活码为多人版，请随意绑定一个uid)")
                        uid = input("UID:")
                        requests.utils.add_dict_to_cookiejar(session.cookies,{"bilibili_ticket":gen_bili_ticket()})
                        data = get_space_info(uid,session)
                        if data["code"] == -404:
                            logger.error("UID不存在")
                            continue
                        name = data["data"]["name"]
                        logger.info(f"UID: {uid} 用户名: {name}")
                        confirm = input("请确认是否为您的账号，一经绑定，无法修改(y/N):")
                        if confirm.lower() != "y":
                            logger.error("绑定失败")
                            continue
                        data = requests.get(f"https://bhyg.bitf1a5h.eu.org/individual?gh_token={gh_token}&mc={get_machine_code()}&uid={uid}").json()
                        if data["success"]:
                            key = data["key"]
                            break
                        else:
                            logger.error("激活失败")
                            logger.error(data["msg"])
                            continue
                        
            else:
                with open("key", "r", encoding="utf-8") as f:
                    key = f.read()
            if not verify(key):
                individual = input("是否为个人使用？(Y/n)")
                if individual.lower() == "n":
                    key = input("本机机器码："+get_machine_code()+"请输入授权码或激活码：")
                    if len(key) == 8:
                        uid = ""
                        logger.info("激活需要绑定您的Bilibili UID，请输入您的UID(若您的激活码为多人版，请随意绑定一个uid)")
                        while True:
                                uid = input("UID:")
                                requests.utils.add_dict_to_cookiejar(session.cookies,{"bilibili_ticket":gen_bili_ticket()})
                                data = get_space_info(uid,session)
                                if data["code"] == -404:
                                    logger.error("UID不存在")
                                    continue
                                name = data["data"]["name"]
                                logger.info(f"UID: {uid} 用户名: {name}")
                                confirm = input("请确认是否为您的账号，一经绑定，无法修改(y/N):")
                                if confirm.lower() != "y":
                                    logger.error("绑定失败")
                                else:
                                    break
                        key = session.get(f"https://bhyg.bitf1a5h.eu.org/activate?code={key}&mc={get_machine_code()}&uid={uid}").json()
                        if key == None:
                            logger.error("激活码无效")
                            logger.info("即将退出")
                            time.sleep(10)
                            return
                    with open("key", "w", encoding="utf-8") as f:
                        f.write(key)
                else:
                    while True:
                        uid = ""
                        logger.info("请确认您已点击Star")
                        gh_token = get_github_token(session)
                        logger.info("激活需要绑定您的Bilibili UID，请输入您的UID(若您的激活码为多人版，请随意绑定一个uid)")
                        uid = input("UID:")
                        requests.utils.add_dict_to_cookiejar(session.cookies,{"bilibili_ticket":gen_bili_ticket()})
                        data = get_space_info(uid,session)
                        if data["code"] == -404:
                            logger.error("UID不存在")
                            continue
                        name = data["data"]["name"]
                        logger.info(f"UID: {uid} 用户名: {name}")
                        confirm = input("请确认是否为您的账号，一经绑定，无法修改(y/N):")
                        if confirm.lower() != "y":
                            logger.error("绑定失败")
                            continue
                        data = requests.get(f"https://bhyg.bitf1a5h.eu.org/individual?gh_token={gh_token}&mc={get_machine_code()}&uid={uid}").json()
                        if data["success"]:
                            key = data["key"]
                            break
                        else:
                            logger.error("激活失败")
                            logger.error(data["msg"])
                            continue
                with open("key", "w", encoding="utf-8") as f:
                    f.write(key)
                if not verify(key):
                    return
            if not os.path.exists("data"):
                os.mkdir("data")
            # 判断是否存在config.json
            if os.path.exists("config.json"):
                is_use_config = input("已存在上一次的配置文件，是否沿用全部或只沿用登录信息（包括风控信息）？(Y/l/n)")
                if is_use_config == "n":
                    logger.info("重新配置")
                    config = {}
                elif is_use_config == "l":
                    logger.info("只沿用登录信息")
                    with open("config.json", "r", encoding="utf-8") as f:
                        config = {}
                        try:
                            config["cookie"] = json.load(f)["cookie"]
                            config["gaia_vtoken"] = json.load(f)["gaia_vtoken"]
                        except:
                            logger.error("读取cookie失败，重新配置")
                            config = {}
                else:
                    if(is_use_config.lower() == "y"):
                        logger.info("使用上次的配置文件")
                    else:
                        logger.info("已默认使用上次的配置文件")
                    # 读取config.json，转为dict并存入config
                    with open("config.json", "r", encoding="utf-8") as f:
                        config = json.load(f)
            else:
                # 不存在则创建config.json
                with open("config.json", "w", encoding="utf-8") as f:
                    f.write("{}")
                config = {}
            os.system(f"start http://127.0.0.1:{port}")
            while True:
                if "cookie" not in config:
                    config["cookie"] = login()
                    with open("config.json", "w", encoding="utf-8") as f:
                        json.dump(config, f)
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) BHYG/0.6.3",
                    "Cookie": config["cookie"]
                }
                user = requests.get("https://api.bilibili.com/x/web-interface/nav", headers=headers)
                user = user.json()
                if(user["data"]["isLogin"]):
                    logger.success("用户 "+user["data"]["uname"]+" 登录成功")
                    if uid != '':
                        if int(uid) != user["data"]["mid"]:
                            logger.error(str(user["data"]["mid"])+"用户不匹配")
                            config.pop("cookie")
                            continue
                    else:
                        logger.success("欢迎您，尊敬的多人版用户")
                    break
                else:
                    logger.error("登录失败")
                    config.pop("cookie")

            bilibili_hyg = BilibiliHyg(config)
            bilibili_hyg.run()
    except KeyboardInterrupt:
        logger.info("已手动退出")
        return
    except Exception as e:
        track = sentry_sdk.capture_exception(e)
        logger.exception("程序出现错误，错误信息："+str(e))
        logger.error("错误追踪ID(可提供给开发者)："+str(track))
        return
    return

if __name__ == "__main__":
    def run(app,port):
        uvicorn.run(app, host="0.0.0.0", port=port, log_level="critical")
    thread = threading.Thread(target=run, args=(app,port,), daemon=True)
    thread.start()
    main()
    from sentry_sdk import Hub
    client = Hub.current.client
    if client is not None:
        client.close(timeout=2.0)
    logger.info("已安全退出，您可以关闭窗口")
    time.sleep(10)