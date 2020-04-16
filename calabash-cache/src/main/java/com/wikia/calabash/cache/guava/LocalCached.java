package com.wikia.calabash.cache.guava;

import java.lang.annotation.Documented;
import java.lang.annotation.ElementType;
import java.lang.annotation.Inherited;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;
import java.util.concurrent.TimeUnit;

@Target({ElementType.METHOD})
@Retention(RetentionPolicy.RUNTIME)
@Inherited
@Documented
public @interface LocalCached {
    String name();

    String key() default "";

    long expireAfterWrite() default 0;

    TimeUnit expireTimeUnit() default TimeUnit.SECONDS;

    long refreshAfterWrite() default 0;

    TimeUnit refreshTimeUnit() default TimeUnit.SECONDS;

    int maximumSize() default Integer.MAX_VALUE;

    boolean cacheNullValue() default false;
}
