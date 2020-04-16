package com.wikia.calabash.cache;

import com.alibaba.fastjson.JSON;
import com.alibaba.fastjson.JSONArray;

import java.lang.reflect.Method;
import java.lang.reflect.Parameter;

public class JsonKeyParser implements KeyParser {

    public String generateKey(String name, String key, Method method, Object[] args) {
        try {
            if (key != null && !key.isEmpty()) {
                return key;
            }
            return JSON.toJSONString(args);
        } catch (Exception e) {
            throw new RuntimeException(e);
        }
    }

    public Object[] parseKey(String key, Method method) {
        try {
            Parameter[] parameters = method.getParameters();
            if (parameters == null || parameters.length == 0) {
                return null;
            }
            Object[] args = new Object[parameters.length];

            JSONArray objects = JSON.parseArray(key);

            for (int i = 0; i < parameters.length; i++) {
                Class<?> argClz = parameters[i].getType();
                args[i] = objects.getObject(i, argClz);
            }

            return args;
        } catch (Exception e) {
            throw new RuntimeException(e);
        }
    }

}
