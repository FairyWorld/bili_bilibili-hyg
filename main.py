# -*- coding: UTF-8 -*-
# Copyright (c) 2023 ZianTT
import base64
import hashlib
import json
import os
import random
import socket
import sys
import time
import requests
from api import BilibiliHyg
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

def run(hyg):
            reset = 0
            while(1):
                hyg.risk = False
                if hyg.risk:
                    status = -1
                status, clickable = hyg.get_ticket_status()
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
                    if hyg.mode == 1:
                        while not hyg.try_create_order():
                            hyg.try_create_order()
                    else:
                        hyg.try_create_order()
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
                time.sleep(hyg.config["status_delay"])
                reset += 2

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
            def get_github_token(session):
                global github_token
                if os.path.exists("gh_token"):
                    with open("gh_token", "r") as f:
                        github_token = f.read()
                    return github_token
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
                gh_token = token["access_token"]
                with open("gh_token", "w") as f:
                    f.write(gh_token)
                return gh_token
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
                        logger.info("请确认您已点击项目主页的Star")
                        gh_token = get_github_token(session)
                        logger.info("激活需要绑定您的Bilibili UID，请输入您的UID(若您的激活码为多人版，请随意绑定一个uid)")
                        uid = input("UID:")
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

            BHYG = BilibiliHyg(config,sentry_sdk)
            run(BHYG)
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