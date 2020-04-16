package com.wikia.calabash.cache;

import java.lang.reflect.Method;

public interface KeyParser {
    String generateKey(String name, String key, Method method, Object[] args);

    Object[] parseKey(String key, Method method);
}
