"""雲端登入（Google、Microsoft）。只用標準函式庫實作 OAuth 2.0 授權碼流程，不需額外安裝套件。

流程：按下登入 -> 導向服務商授權頁 -> 回到 /auth/<provider>/callback/ -> 用 code 換 token
      -> 取得使用者資料 -> 建立或對應使用者 -> 登入。
"""
import json
import secrets
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.models import User
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme

from .models import Profile, SocialIdentity

PROVIDERS = {
    "google": {
        "name": "Google",
        "authorize": "https://accounts.google.com/o/oauth2/v2/auth",
        "token": "https://oauth2.googleapis.com/token",
        "userinfo": "https://openidconnect.googleapis.com/v1/userinfo",
        "extra": {"prompt": "select_account"},
    },
    "microsoft": {
        "name": "Microsoft",
        "authorize": "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize",
        "token": "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
        "userinfo": "https://graph.microsoft.com/oidc/userinfo",
        "extra": {"response_mode": "query", "prompt": "select_account"},
    },
}


def _conf(key):
    return settings.SOCIAL_AUTH.get(key, {})


def is_configured(key):
    c = _conf(key)
    return bool(c.get("client_id") and c.get("secret"))


def provider_list():
    keys = ["google"]
    return [
        {
            "key": k,
            "name": PROVIDERS[k]["name"],
            "configured": is_configured(k),
        }
        for k in keys
    ]


def _url(key, which):
    return PROVIDERS[key][which].format(tenant=_conf(key).get("tenant", "common"))


def _redirect_uri(request, key):
    path = reverse("social_callback", args=[key])
    base = settings.SOCIAL_REDIRECT_BASE.rstrip("/")
    return f"{base}{path}" if base else request.build_absolute_uri(path)


def _post(url, data):
    req = urllib.request.Request(
        url, data=urllib.parse.urlencode(data).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get(url, token):
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def start(request, provider):
    """第一步：導向服務商的授權頁。"""
    if provider not in PROVIDERS:
        messages.error(request, "不支援的登入方式")
        return redirect("login")
    if not is_configured(provider):
        messages.error(request, f"{PROVIDERS[provider]['name']} 登入還沒有設定，請先看 README 的「雲端登入設定」。")
        return redirect("login")

    state = secrets.token_urlsafe(24)
    request.session["oauth_state"] = state
    request.session["oauth_next"] = request.GET.get("next", "")
    params = {
        "client_id": _conf(provider)["client_id"],
        "redirect_uri": _redirect_uri(request, provider),
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        **PROVIDERS[provider]["extra"],
    }
    return redirect(f"{_url(provider, 'authorize')}?{urllib.parse.urlencode(params)}")


def callback(request, provider):
    """第二步：服務商導回來，換取 token 並登入。"""
    if provider not in PROVIDERS or not is_configured(provider):
        return redirect("login")

    expected = request.session.pop("oauth_state", "")
    nxt = request.session.pop("oauth_next", "")
    got = request.GET.get("state", "")
    if request.GET.get("error"):
        messages.error(request, "你取消了登入，或服務商拒絕了授權。")
        return redirect("login")
    if not expected or not secrets.compare_digest(expected, got):
        messages.error(request, "登入驗證失敗（state 不符），請重新操作一次。")
        return redirect("login")

    code = request.GET.get("code", "")
    try:
        token = _post(_url(provider, "token"), {
            "code": code,
            "client_id": _conf(provider)["client_id"],
            "client_secret": _conf(provider)["secret"],
            "redirect_uri": _redirect_uri(request, provider),
            "grant_type": "authorization_code",
        })
        info = _get(PROVIDERS[provider]["userinfo"], token["access_token"])
    except (urllib.error.URLError, ValueError, KeyError):
        messages.error(request, f"無法完成 {PROVIDERS[provider]['name']} 登入，請稍後再試或改用帳號密碼。")
        return redirect("login")

    uid = str(info.get("sub", ""))
    email = (info.get("email") or "").strip().lower()
    if not uid:
        messages.error(request, "服務商沒有回傳使用者資料。")
        return redirect("login")

    domain = email.rsplit("@", 1)[-1] if "@" in email else ""
    allowed = settings.SOCIAL_ALLOWED_DOMAINS
    if allowed and domain not in allowed:
        messages.error(request, f"只開放學校信箱登入（{'、'.join('@' + d for d in allowed)}），你使用的是 {email or '未提供信箱'}。")
        return redirect("login")

    # 信箱經過服務商驗證，才允許對應到既有帳號
    verified = info.get("email_verified") is True or (provider == "microsoft" and bool(allowed))
    user, created = find_or_create_user(provider, uid, email, info, verified)
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    messages.success(request, f"歡迎加入課拼，{display(user)}！" if created else f"歡迎回來，{display(user)}")

    if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return redirect(nxt)
    return redirect("home")


def display(user):
    return (user.last_name + user.first_name) or user.get_username()


def _split_name(info):
    family, given = info.get("family_name"), info.get("given_name")
    if family or given:
        return family or "", given or ""
    name = (info.get("name") or "").strip()
    if name and " " not in name and len(name) <= 4:  # 中文姓名：第一個字當姓
        return name[0], name[1:]
    return "", name


def find_or_create_user(provider, uid, email, info, verified):
    ident = SocialIdentity.objects.select_related("user").filter(provider=provider, uid=uid).first()
    if ident:
        return ident.user, False

    user = User.objects.filter(email__iexact=email).first() if (email and verified) else None
    created = False
    if not user:
        last, first = _split_name(info)
        base = (email or f"{provider}_{uid}")[:140]
        username, n = base, 1
        while User.objects.filter(username=username).exists():
            n += 1
            username = f"{base}{n}"
        user = User(username=username, email=email, last_name=last[:150], first_name=first[:150])
        user.set_unusable_password()
        user.save()
        local = email.split("@")[0] if "@" in email else ""
        Profile.objects.create(user=user, role="student", student_no=local if local.isdigit() else "")
        created = True
    SocialIdentity.objects.create(user=user, provider=provider, uid=uid, email=email)
    return user, created
