#include "py/runtime.h"
#include "mbedtls/pk.h"
#include "mbedtls/md.h"
#include "ota_key.h"

static mp_obj_t ota_verify(mp_obj_t manifest_obj, mp_obj_t signature_obj) {
    mp_buffer_info_t manifest, signature;
    mp_get_buffer_raise(manifest_obj, &manifest, MP_BUFFER_READ);
    mp_get_buffer_raise(signature_obj, &signature, MP_BUFFER_READ);
    if (manifest.len > 16384 || signature.len < 8 || signature.len > 80) {
        return mp_const_false;
    }
    unsigned char hash[32];
    mbedtls_pk_context key;
    mbedtls_pk_init(&key);
    int result = mbedtls_pk_parse_public_key(&key, ota_public_key, sizeof(ota_public_key));
    if (result == 0 && mbedtls_pk_can_do(&key, MBEDTLS_PK_ECDSA)) {
        result = mbedtls_md(mbedtls_md_info_from_type(MBEDTLS_MD_SHA256),
                           manifest.buf, manifest.len, hash);
        if (result == 0) {
            result = mbedtls_pk_verify(&key, MBEDTLS_MD_SHA256, hash, sizeof(hash),
                                      signature.buf, signature.len);
        }
    } else {
        result = -1;
    }
    mbedtls_pk_free(&key);
    return mp_obj_new_bool(result == 0);
}
static MP_DEFINE_CONST_FUN_OBJ_2(ota_verify_obj, ota_verify);
static const mp_rom_map_elem_t ota_verify_globals_table[] = {
    { MP_ROM_QSTR(MP_QSTR___name__), MP_ROM_QSTR(MP_QSTR_ota_verify) },
    { MP_ROM_QSTR(MP_QSTR_verify), MP_ROM_PTR(&ota_verify_obj) },
};
static MP_DEFINE_CONST_DICT(ota_verify_globals, ota_verify_globals_table);
const mp_obj_module_t ota_verify_module = {
    .base = { &mp_type_module },
    .globals = (mp_obj_dict_t *)&ota_verify_globals,
};
MP_REGISTER_MODULE(MP_QSTR_ota_verify, ota_verify_module);
