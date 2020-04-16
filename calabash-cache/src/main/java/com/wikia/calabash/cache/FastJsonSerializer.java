package com.wikia.calabash.cache;

import com.alibaba.fastjson.JSON;
import com.google.common.base.Strings;
import org.springframework.stereotype.Component;

import java.lang.reflect.Type;

@Component
public class FastJsonSerializer implements Serializer {
    @Override
    public String serialize(Object o) {
        try {
            return JSON.toJSONString(o);
        } catch (Exception e) {
            throw new IllegalArgumentException(String.format("redis jackson serialize fail:%s", o));
        }
    }

    @Override
    public Object deserialize(String s, Type type) {
        try {
            if (Strings.isNullOrEmpty(s)) {
                return null;
            }
            return JSON.parseObject(s, type);
        } catch (Exception e) {
            throw new IllegalArgumentException(String.format("redis jackson deserialize fail:%s, %s", s, type));
        }
    }
}
