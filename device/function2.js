if (msg.payload.includes("True")) {
    msg.payload = 1;
    return msg;
}
return null;
