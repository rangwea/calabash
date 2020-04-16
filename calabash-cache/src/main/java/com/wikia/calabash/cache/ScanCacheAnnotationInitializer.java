package com.wikia.calabash.cache;

import com.wikia.calabash.cache.guava.LocalCached;
import com.wikia.calabash.cache.redis.RedisCached;
import com.wikia.calabash.cache.util.AopTargetUtils;
import org.springframework.aop.support.AopUtils;
import org.springframework.beans.BeansException;
import org.springframework.beans.factory.config.BeanPostProcessor;
import org.springframework.core.annotation.AnnotationUtils;
import org.springframework.stereotype.Component;

import javax.annotation.Resource;
import java.lang.reflect.Method;

@Component
public class ScanCacheAnnotationInitializer implements BeanPostProcessor {
    @Resource
    private CacheManager cacheManager;

    @Override
    public Object postProcessAfterInitialization(Object bean, String beanName) throws BeansException {
        Class<?> targetClass;
        if (AopUtils.isAopProxy(bean)) {
            targetClass = AopUtils.getTargetClass(bean);
        } else {
            targetClass = bean.getClass();
        }
        Method[] methods = targetClass.getMethods();
        for (Method method : methods) {
            RedisCached redisCached = AnnotationUtils.findAnnotation(method, RedisCached.class);
            if (redisCached != null) {
                cacheManager.addRedisCache(redisCached, method);
            }
            LocalCached localCached = AnnotationUtils.findAnnotation(method, LocalCached.class);
            if (localCached != null) {
                try {
                    cacheManager.addLocalCache(localCached, method, AopTargetUtils.getTarget(bean));
                } catch (Exception e) {
                    e.printStackTrace();
                }
            }
        }
        return bean;
    }
}
